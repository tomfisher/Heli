"""[INFO]
Rebuilds the database and performs the desired data augmentation

To do:
- Multiprocessing support to rebuild faster
- Extract helicopter from video then paste on lots of negatives
"""

import argparse
# import imutils
import time
import cv2
# import csv
import psutil
import os
# import copy
import pickle
from glob import glob
import numpy as np
import video_tools as vt


def main():
    # Rebuild the crop folders
    clean_crop_directory(PATH_CROP_FOLDER)
    
    # Load the bboxes
    with open(PATH_EXTRAPOLATED_BBOX, 'rb') as f:
        bbox_heli_ground_truth = pickle.load(f)
    
    video_stream, nb_frames, frame_width, frame_height = import_stream(PATH_VIDEO)
    vs2 = cache_video(video_stream, 'list')
    
    # Rebuild the crops
    print("[INFO] Starting {} iterations".format(len(iteration_dict)))
    first_bbox = min(bbox_heli_ground_truth.keys())
    last_bbox = max(bbox_heli_ground_truth.keys())
    print("[INFO] Using bbox frames {} to {}".format(first_bbox, last_bbox))
    
    # Start going through the frames
    for frame_number in range(nb_frames):
        t0 = time.perf_counter()
        # frame = vs.read()[1] # No cache
        current_frame = vs2[frame_number].copy()  # Prevents editing the original frames!
        t1 = time.perf_counter()
        # Skip all the frames that do not have a Bbox
        if frame_number < max(first_bbox, 25):  # skip first sec for luminosity adjustments
            continue
        if frame_number > min(nb_frames - 2, last_bbox):
            break
        # Create a 0 based index that tracks how many bboxes we have gone through
        bbox_frame_number = frame_number - first_bbox  # Starts at 0, automatically
        if bbox_frame_number%STRIDE == 0:
            # Get reference for background substitution --> assumes the camera is steady
            #reference_frame = -1 if frame_number < nb_frames/2 else 0
            #reference_frame = vs2[reference_frame].copy()  # First or last frame
            # Load the corresponding frame
            positive_image = vs2[frame_number].copy()
            
            # Ground Truth data
            x_gt, y_gt, w_gt, h_gt = bbox_heli_ground_truth[frame_number]  # frame id
            xc, yc = x_gt + w_gt//2, y_gt + h_gt//2

            # IV.2.2 Cropping - populate both folders
            # IV.2.2.1 First option: NN_SIZE crop
            # Limit the size of the crop
            x_start = max(0, xc - NN_SIZE[0]//2)
            x_end = min(frame_width, xc + NN_SIZE[0]//2)
            y_start = max(0, yc - NN_SIZE[1]//2)
            y_end = min(frame_height, yc + NN_SIZE[1]//2)
            crop = frame[y_start:y_end, x_start:x_end]
            crop = nn_size_crop(crop, NN_SIZE, (xc, yc), frame.shape)
            out_path = os.path.join(PATH_CROPS_NN_SIZE, TIMESTAMP+str(frame_number)+EXT)
            cv2.imwrite(out_path, crop)
            # IV.2.2.2 Second option: (square) bbox crop resized to NN_SIZE
            s = max(w, h) if max(w, h) % 2 == 0 else max(w, h) + 1  # even only
            x_start = max(0, xc - s//2)
            x_end = min(frame_width, xc + s//2)
            y_start = max(0, yc - s//2)
            y_end = min(frame_height, yc + s//2)
            crop = frame[y_start:y_end, x_start:x_end]
            crop = nn_size_crop(crop, (s, s), (xc, yc), frame.shape)  # pad to (s, s)
            # Then only we resize to NN_SIZE
            crop = cv2.resize(crop, NN_SIZE)  # Resize to NN input size
            out_path = os.path.join(PATH_CROP_RESIZED_TO_NN, TIMESTAMP+str(frame_number)+EXT)
            cv2.imwrite(out_path, crop)
            # IV.2.2.3 Create a negative image - no helico
            crop = crop_negative(frame, NN_SIZE, (xc, yc))
            out_path = os.path.join(PATH_NEGATIVES, TIMESTAMP+str(counter_crop)+EXT)
            cv2.imwrite(out_path, crop)

    # Augment the data after all the pos/pos/neg have been created
    # List all the pictures & read info file
    images = sorted([img for img in glob.glob(PATH_POSITIVE+'*')])  # Glob glob is not deterministic
    negative_images = sorted([img for img in glob.glob(PATH_NEGATIVE+'*')])
    # Read the info file
    info = {}
    with open(PATH_VIDEO+'Info.txt') as f:
        data = csv.reader(f, delimiter=':')
        for line in data:
            info[line[0]] = line[1]
    print(info)
    extractor = vt.extract.extractor(BLUR, CANNY_THRESH_1, CANNY_THRESH_2, MASK_DILATE_ITER, MASK_ERODE_ITER, max_area=MAX_AREA)
    
    # Generate the extracted helicopter pictures
    timing = []
    list_max_area = []
    for index, img in enumerate(images):
        img_array = cv2.imread(img, cv2.IMREAD_UNCHANGED)
        extracted_area, extracted_image = extractor.extract_positive(img_array)
        list_max_area.append(extracted_area)
        if extracted_area:
            cv2.imwrite(PATH_EXTRACTED+str(index)+EXT, extracted_image)
    
    # Blend with negative images
    extracted_images = sorted([img for img in glob.glob(PATH_EXTRACTED+'*')])
    for count in range(TOTAL_COUNT):
        random_neg_index = np.random.randint(len(negative_images))
        neg_img_array = cv2.imread(negative_images[random_neg_index], cv2.IMREAD_UNCHANGED)
        # Select a random positive image to blend with
        random_crop_index = np.random.randint(len(extracted_images))
        img_array = cv2.imread(extracted_images[random_crop_index], cv2.IMREAD_UNCHANGED)  # RGB 4 channels
        if np.random.rand() <= HELICO_FREQUENCY:
            blended_image = extractor.blend_with_negative(neg_img_array, img_array, rotations=ROTATIONS, scaling=SCALING)
            Y_labels.append(['Helicopter', info['Model']])
        else:
            blended_image = neg_img_array
            Y_labels.append(['Negative', 'None'])
        #blended_image = cv2.cvtColor(blended_image, cv2.COLOR_RGB2BGR)
        cv2.imwrite(PATH_AUGMENTED+str(count)+EXT, blended_image)
    
    # Output all the labels to a file
    with open(PATH_AUGMENTED+TS+'_labels_aug.txt', 'w') as f:
        out = csv.writer(f)
        for label in Y_labels:
            out.writerow(label)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--count", type=int, default=100, help="Number of images per folder")
    ap.add_argument("-h", "--helico_frequency", type=float, default=0.5, help="Frequency of positive pictures in the augmented data")
    ap.add_argument("-s", "--stride", type=int, default=25, help="How often is an original frame used to augment the data")
    ap.add_argument("-r", "--rotation", type=str, default='(0, 5)', help="Tuple of normal distribution of rotations")
    ap.add_argument("-z", "--zoom", type=str, default='(1, 0.5)', help="Zoom in factor. Has to be >= 1 or ignored")
    args = vars(ap.parse_args())
    
    PATH_IMAGES = '/home/alex/Desktop/Helico/0_Database/RPi_import/'
    FOLDERS = [folder for folder in glob.glob(PATH_IMAGES+'*') if os.path.isdir(folder)]

    # Parameters for the positive images extraction
    BLUR = 1
    CANNY_THRESH_1 = 10
    CANNY_THRESH_2 = 200
    MASK_DILATE_ITER = 4
    MASK_ERODE_ITER = 4
    MAX_AREA = 62*10
    # I.2. Initialize a dictionary that maps strings to their corresponding
    OPENCV_OBJECT_TRACKERS = {
        "csrt": cv2.TrackerCSRT_create,
        "kcf": cv2.TrackerKCF_create,
        "boosting": cv2.TrackerBoosting_create,
        "mil": cv2.TrackerMIL_create,
        "tld": cv2.TrackerTLD_create,
        "medianflow": cv2.TrackerMedianFlow_create,
        "mosse": cv2.TrackerMOSSE_create
    }
    TRACKER = "csrt"
    # args["video"] = "/home/alex/Desktop/Helico/0_Database/RPi_import/"\
    # "190624_202327/190624_202327_helico_1920x1080_45s_25fps_T.mp4"
    COLOR = {'WHITE': (255, 255, 255), 'BLUE': (255, 0, 0), 'GREEN': (0, 255, 0), 'RED': (0, 0, 255), 'BLACK': (0, 0, 0)}
    STRIDES = 25  # Number of frames with bbox to skip
    NN_SIZE = (224, 224)  # Should be guess by the NN but anyway
    EXT = '.png'
    TOTAL_COUNT = 100  # Number of images to create per folder
    HELICO_FREQUENCY = 0.5
    # Normal distributions
    ROTATIONS = (0, 5)
    SCALING = (1, 0.5)  # Truncated to be >= 1
        
    for folder in FOLDERS:
        PATH_VIDEO = [video for video in glob.glob(folder+'/*') if video[-4:] == '.mp4']
        if len(PATH_VIDEO) > 1:
            continue  # newVideo folder
        
        # Create the expected folder structure
        PATH_VIDEO = PATH_VIDEO[0]
        VIDEO_FOLDER = os.path.split(PATH_VIDEO)[0]
        TIMESTAMP = os.path.split(PATH_VIDEO)[1][:14]
        PATH_SOURCE_BBOX = os.path.join(VIDEO_FOLDER, TIMESTAMP+"sourceBB.pickle")
        PATH_EXTRAPOLATED_BBOX = os.path.join(VIDEO_FOLDER, TIMESTAMP+"extrapolatedBB.pickle")
        PATH_CROP_FOLDER = os.path.join(os.path.split(PATH_VIDEO)[0], TIMESTAMP+'NN_crops')
        PATH_CROPS_NN_SIZE = os.path.join(PATH_CROP_FOLDER, 'nnSizeCrops')
        PATH_CROP_RESIZED_TO_NN = os.path.join(PATH_CROP_FOLDER, 'cropsResizedToNn')
        
        PATH_NEGATIVES = os.path.join(PATH_CROP_FOLDER, 'Negatives')
        PATH_EXTRACTED = os.path.join(PATH_CROP_FOLDER, 'Extracted_helicopters')
        PATH_AUGMENTED = os.path.join(PATH_CROP_FOLDER, 'Augmented_data')
        METHOD = 'nnSizeCrops'
        PATH_POSITIVE = os.path.join(PATH_CROP_FOLDER, METHOD)

        # main will rebuild one folder. It has to be run multiple times.
        main()