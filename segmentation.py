import os
from glob import glob
import matplotlib.pyplot as plt
import torch
import torch.backends.cudnn as cudnn
import torchvision.transforms as transforms
import numpy as np
from scipy.ndimage import imread
from scipy.misc import imsave
import sys
import cv2

from skimage.segmentation import slic 
from skimage.segmentation import mark_boundaries
from skimage.util import img_as_float
from skimage import io
from PIL import Image

sys.path.append('superpixel_fcn/')

from loss import *
import models as models
import flow_transforms as flow_transforms

sys.path.append('../')

cityscapes_dir = '../vcg_natural/cityscape'
image_dir = 'leftImg8bit/train'
label_dir = 'gtFine/train'
image_suffix = '.png'
label_suffix = '_gtFine_labelIds.png'

path_to_pretrained = 'superpixel_fcn/pretrain_ckpt/SpixelNet_bsd_ckpt.tar'

save_path = 'output/slic'

downsize = 16


# Gets a list of all image/label pairs in the data directory
def get_image_label_pairs(data_dir=cityscapes_dir):
    image_root = os.path.join(data_dir, image_dir)
    label_root = os.path.join(data_dir, label_dir)
    # For each directory in image root, get all files with the given suffix
    image_paths = [glob(os.path.join(image_root, d, '*' + image_suffix)) for d in os.listdir(image_root)]
    # Flatten the list of lists
    image_paths = [item for sublist in image_paths for item in sublist]
    
    # Do the same for the label paths
    label_paths = [glob(os.path.join(label_root, d, '*' + label_suffix)) for d in os.listdir(label_root)]
    label_paths = [item for sublist in label_paths for item in sublist]
    
    # Order both lists
    image_paths.sort()
    label_paths.sort()
    
    # store each image-label pair as a list of lists
    image_label_pairs = [[image_paths[i], label_paths[i]] for i in range(len(image_paths))]
    
    return image_label_pairs

# Prepares a list of images and labels for the model
def prepare_data(image_label_pairs):
    images = []
    labels = []
    for image_path, label_path in image_label_pairs:
        image = plt.imread(image_path)
        label = plt.imread(label_path)
        
        # Convert label from float to integers, where label n is the nth largest value
        vals = np.unique(label)
        # Assign each value in the label to its index in the sorted list of unique values
        for i in range(len(vals)):
            label[label == vals[i]] = i
        
        images.append(image)
        labels.append(label.astype(int))
    return images, labels

def get_slic_superpixels(images, numSegments=100):
    spixels = []
    for i, image in enumerate(images):
        if i % 5 == 0:
            print(i)
        segments = slic(image, n_segments = numSegments, sigma = 5)
        spixels.append(segments)
    return spixels
    
# Return superpixels generated by superpixel CNN
def get_cnn_superpixels(image_paths):
    # Prepare the model
    network_data = torch.load(path_to_pretrained, map_location=torch.device('cpu'))
    print("=> using pre-trained model '{}'".format(network_data['arch']))
    model = models.__dict__[network_data['arch']]( data = network_data) #.cuda()
    model.eval()
    
    cudnn.benchmark = True
    
    spixel_maps = []
    
    for n in range(len(image_paths)):
        if n % 5 == 0:
            print(n)
        spixel_maps.append(test(model, image_paths, save_path, n))
    
    return spixel_maps
    
@torch.no_grad()
def test(model, img_paths, save_path, idx):
      # Data loading code
    input_transform = transforms.Compose([
        flow_transforms.ArrayToTensor(),
        transforms.Normalize(mean=[0,0,0], std=[255,255,255]),
        transforms.Normalize(mean=[0.411,0.432,0.45], std=[1,1,1])
    ])

    img_file = img_paths[idx]
    
    load_path = img_file
    
    imgId = os.path.basename(img_file)[:-4]

    # may get 4 channel (alpha channel) for some format
    img_ = imread(load_path)[:, :, :3]
    
    H, W, _ = img_.shape
    H_, W_  = int(np.ceil(H/16.)*16), int(np.ceil(W/16.)*16)

    # get spixel id
    n_spixl_h = int(np.floor(H_ / downsize))
    n_spixl_w = int(np.floor(W_ / downsize))

    spix_values = np.int32(np.arange(0, n_spixl_w * n_spixl_h).reshape((n_spixl_h, n_spixl_w)))
    spix_idx_tensor_ = shift9pos(spix_values)

    spix_idx_tensor = np.repeat(
      np.repeat(spix_idx_tensor_, downsize, axis=1), downsize, axis=2)

    spixeIds = torch.from_numpy(np.tile(spix_idx_tensor, (1, 1, 1, 1))).type(torch.float) #.cuda()

    n_spixel =  int(n_spixl_h * n_spixl_w)

    img = cv2.resize(img_, (W_, H_), interpolation=cv2.INTER_CUBIC)
    img1 = input_transform(img)
    ori_img = input_transform(img_)

    # compute output
    output = model(img1.unsqueeze(0))

    # assign the spixel map
    curr_spixl_map = update_spixl_map(spixeIds, output)
    ori_sz_spixel_map = F.interpolate(curr_spixl_map.type(torch.float), size=( H_,W_), mode='nearest').type(torch.int)
    
    return ori_sz_spixel_map[0][0].numpy()
    
    # mean_values = torch.tensor([0.411, 0.432, 0.45], dtype=img1.cuda().unsqueeze(0).dtype).view(3, 1, 1)
    mean_values = torch.tensor([0.411, 0.432, 0.45], dtype=img1.unsqueeze(0).dtype).view(3, 1, 1)
    spixel_viz, spixel_label_map = get_spixel_image((ori_img + mean_values).clamp(0, 1), ori_sz_spixel_map.squeeze(), n_spixels= n_spixel,  b_enforce_connect=True)

    # save spixel viz
    if not os.path.isdir(os.path.join(save_path, 'spixel_viz')):
        os.makedirs(os.path.join(save_path, 'spixel_viz'))
    spixl_save_name = os.path.join(save_path, 'spixel_viz', imgId + '_sPixel.png')
    imsave(spixl_save_name, spixel_viz.transpose(1, 2, 0))

# Converts a superpixel map and ground truth label to a superpixellized segmentation
def get_superpixel_labels(spixel_map, ground_truth, append=''):
    new_labels = []
    
    # for each image
    for i in range(len(spixel_map)):
        if i % 5 == 0:
            print(i)
        
        spixel_image = spixel_map[i]
        gt = ground_truth[i]
        spixellized_label = np.zeros(spixel_image.shape)
        spixel_ids = np.unique(spixel_image)
        # For each superpixel, assign the most common label
        for j in spixel_ids:
            spixellized_label[spixel_image == j] = np.bincount(gt[spixel_image == j]).argmax()
            
        new_labels.append(spixellized_label)
        
        # Save the superpixelized label for visualization
        plt.imsave(save_path + '/superpixellized/superpixelized_label_' + append + f'{i}.png', spixellized_label)
        
    return new_labels


# Evaluate the superpixel segmentation relative to the ground truth segmentation by mean IoU
def evaluate_superpixel_segmentation(spixel_labels, ground_truth):
    ious = np.zeros(len(spixel_labels))
    ious_unweighted = np.zeros(len(spixel_labels))
    H,W = ground_truth[0].shape
    # For each image
    for i in range(len(spixel_labels)):
        if i % 5 == 0:
            print(i)
            
        spixellized_label = spixel_labels[i]
        gt = ground_truth[i]
        ids = np.unique(gt)
        # For each label
        for j in ids:
            spixellized_mask = (spixellized_label == j)
            gt_mask = (gt == j)
            iou = np.sum(spixellized_mask & gt_mask) / np.sum(spixellized_mask | gt_mask)
            # add the iou to ious proportional to the number of pixels in the ground truth mask
            ious[i] += iou * np.sum(gt_mask) / (H * W)
            ious_unweighted[i] += iou / len(ids)
            
    print(ious)
    print(ious_unweighted)
    return np.mean(ious), np.mean(ious_unweighted)

pairs = np.array(get_image_label_pairs()[0:100])
print("Pairs gathered.")
img_paths, lab_paths = pairs.T

# print("Getting superpixel labels.")
# spixel_maps = get_cnn_superpixels(img_paths, lab_paths)
# print("Superpixel labels gathered.")

images, labels = prepare_data(pairs)
print("Data prepared.")

mean_iou, mean_iou_unweighted = evaluate_superpixel_segmentation(labels, labels)
print("Mean IoU: ", mean_iou)
print("Mean IoU unweighted: ", mean_iou_unweighted)

# H, W, _ = images[0].shape
# H_, W_  = int(np.ceil(H/16.)*16), int(np.ceil(W/16.)*16)

# # get spixel id
# n_spixl_h = int(np.floor(H_ / downsize))
# n_spixl_w = int(np.floor(W_ / downsize))
# n_spixl_total = n_spixl_h * n_spixl_w

# for nspixels in [100, 300, 500, 1000, n_spixl_total]:
#     print(f"Getting spixels for {nspixels}")
#     spixels = get_slic_superpixels(images, nspixels)
#     print("Done")
    
#     print(f"Getting superpixel labels for {nspixels}.")
#     spixel_labels = get_superpixel_labels(spixels, labels, append=f'{nspixels}_')
#     print("Superpixel labels gathered.")
    
#     print(f"Evaluating superpixel segmentation for {nspixels}.")
#     mean_iou, mean_iou_unweighted = evaluate_superpixel_segmentation(spixel_labels, labels)
#     print(f"Mean IoU: {mean_iou}")
#     print(f"Mean IoU unweighted: {mean_iou_unweighted}")
#     print("Done")
    

# print("Getting superpixelized labels.")
# new_labels = get_superpixel_labels(spixel_maps, labels)
# print("Superpixelized labels gathered.")

# print("Evaluating superpixel segmentation.")
# miou, miou_u = evaluate_superpixel_segmentation(new_labels, labels)
# print(f"Final mean IoU: {miou}")
# print(f"Final mean IoU unweighted: {miou_u}")
