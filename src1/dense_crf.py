'''
This module creates a dense reconstruction of the 3D Scene from the sparse 3D points
estimated from the bundle adjustment module. It initializes a CRF model based on the
sparse points and the input RGB image.
'''

import os
import cv2
import config
import argparse
import numpy as np
from plane_sweep import plane_sweep
from pydensecrf import densecrf as dcrf
from pydensecrf.utils import create_pairwise_bilateral, unary_from_softmax

def compute_unary_image(unary, depth_samples, outfile):

	gd = np.argmin(unary, axis=0)
	gd_im = np.zeros((unary.shape[1], unary.shape[2]))
	for i in range(unary.shape[1]):
		for j in range(unary.shape[2]):
			gd_im[i,j] = ((depth_samples[gd[i,j]] - np.min(depth_samples)) * 255.0) / (np.max(depth_samples) - np.min(depth_samples))

	cv2.imwrite(outfile, gd_im)

def DenseCRF(unary, img, depth_samples, params, folder, max_depth, min_depth, outfile='depth_map.png', show_wta=False):
    
    labels = unary.shape[0]
    iters = params['iters']
    weight = params['weight']
    pos_std = params['pos_std']
    rgb_std = params['rgb_std']
    max_penalty = params['max_penalty']
    
    # Get initial crude depth map from photoconsistency
    if show_wta :
    	compute_unary_image(unary, depth_samples, outfile=f'../output/cost_volume_{depth_samples.shape[0]}_wta.png')
    
    # Normalize values for each pixel location
    for r in range(unary.shape[1]):
    	for c in range(unary.shape[2]):
    		if np.sum(unary[:, r, c]) <= 1e-9:
    			unary[:, r, c] = 0.0
    		else:
    			unary[:, r, c] = unary[:, r, c]/np.sum(unary[:, r, c])
    
    # Convert to class probabilities for each pixel location
    unary = unary_from_softmax(unary)
    
    d = dcrf.DenseCRF2D(img.shape[1], img.shape[0], labels)
    
    # Add photoconsistency score as uanry potential. 16-size vector
    # for each pixel location
    d.setUnaryEnergy(unary)
    # Add color-dependent term, i.e. features are (x,y,r,g,b)
    d.addPairwiseBilateral(sxy=pos_std, srgb=rgb_std, rgbim=img, compat=np.array([weight, labels*max_penalty]), kernel=dcrf.DIAG_KERNEL, normalization=dcrf.NORMALIZE_SYMMETRIC)
    
    # Run inference steps
    Q = d.inference(iters)
    
    # Extract depth values. Map to [0-255]
    MAP = np.argmax(Q, axis=0).reshape((img.shape[:2]))
    depth_map = np.zeros((MAP.shape[0], MAP.shape[1]))
    
    for i in range(MAP.shape[0]):
    	for j in range(MAP.shape[1]):
    		depth_map[i,j] = depth_samples[MAP[i,j]]
    
    min_val = np.min(depth_map)
    max_val = np.max(depth_map)
    
    for i in range(MAP.shape[0]):
    	for j in range(MAP.shape[1]):
    		depth_map[i,j] = ((depth_map[i,j] - min_val)/(max_val - min_val)) * 255.0
    
    # Upsampling depth map
    # depth_map = cv2.resize(depth_map, (config.CAMERA_PARAMS['cx'] * 2,config.CAMERA_PARAMS['cy'] * 2), interpolation=cv2.INTER_LINEAR)
    cv2.imwrite("output/depth_map.png", depth_map)

def dense_depth(args) :

	folder = args.folder
	num_samples = int(args.nsamples)
	pc_path = args.pc
	show_wta = args.show_wta

	scale = int(args.scale)
	max_depth = float(args.max_d)
	min_depth = float(args.min_d)
	patch_radius = int(args.patch_rad)

	pc_score = 0
	if pc_path is not None :

		load_d = np.load(pc_path)
		folder = load_d['dir']
		min_depth = load_d['min_d']
		max_depth = load_d['max_d']
		pc_score = load_d['pc_cost']
		num_samples = pc_score.shape[0]

	# Create depth samples in the specified depth range
	depth_samples = np.zeros(num_samples)
	step = step = 1.0 / (num_samples - 1.0)

	for val in range(num_samples):
		sample = (max_depth * min_depth) / (max_depth - (max_depth - min_depth) * val * step)
		depth_samples[val] = config.CAMERA_PARAMS['fx']/sample
		# depth_samples[val] = sample

	# Get reference image
	file = ''
	for f in sorted(os.listdir(config.IMAGE_DIR)):
		if f.endswith('.png') or f.endswith('.jpg'):
			file = f
			break

	ref_img = cv2.imread(os.path.join(config.IMAGE_DIR.format(folder), file))
  
	for s in range(scale):
		ref_img = cv2.pyrDown(ref_img)
	# Mean shifting image
	ref_img = cv2.pyrMeanShiftFiltering(ref_img, 20, 20, 1)

	ref_img = cv2.cvtColor(ref_img, cv2.COLOR_BGR2Lab)

	if pc_path is None :

		# Perform plane sweep to calculate photo-consistency loss
		outfile = f'../output/cost_volume_{depth_samples.shape[0]}'
		print("Calculating photoconsistency score...")
		pc_score = plane_sweep(folder, outfile, depth_samples, min_depth, max_depth, scale, patch_radius)
		print("Finished computing photoconsistency score...")

	outfile = f'../output/cost_volume_{depth_samples.shape[0]}__{config.CRF_PARAMS["rgb_std"]}_depth_map.png'
	crf_params = dict()
	crf_params['iters'] = int(args.iters)
	crf_params['pos_std'] = tuple(float(x) for x in args.p_std.split(','))
	crf_params['rgb_std'] = tuple(float(x) for x in args.c_std.split(','))
	crf_params['weight'] = float(args.wt)
	crf_params['max_penalty'] = float(args.max_p)

	# Use photoconsistency score as unary potential
	print("Applying Dense CRF to smoothen depth map...")
	depth_map = DenseCRF(pc_score, ref_img, depth_samples, crf_params, folder, max_depth, min_depth, outfile, show_wta)
	print("Finished solving CRF...")



	dense_depth(args)
