# Instructions

## File structure:
tkaminsky

|

|--segmentation.py

|

|--superpixel_fcn

|

|--output

|

|--environment.yml

|...

vcg_natural

|--cityscape

|  |

|  |--gtFine

|  |

|  |--leftImg8bit

| ...

## Setup

1. Download the conda environment by running
```
conda env create -f environment.yml
```

2. Activate the environment using

```
conda activate vcg
```

3. Install the requisite library for superpixel_fcn with the following command:

```
git clone https://github.com/fuy34/superpixel_fcn.git
```

4. If you don't already have the cityscapes dataset, download it at https://www.cityscapes-dataset.com/login/ and store it using the directory structure specified above.

5. Adjust file paths as needed

6. Function descriptions: TBD