# clip_model.py
import os
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

import torch
import open_clip
import numpy as np
import cv2
from PIL import Image

device = "cpu"

model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32",
    pretrained="openai"
)
# model, _, preprocess = open_clip.create_model_and_transforms(
#     "ViT-L-14",
#     pretrained="openai"
# )
# model, _, preprocess = open_clip.create_model_and_transforms(
#     "ViT-B-16",
#     pretrained="openai"
# )

model.eval()

def extract_image_feature(img):

    image = Image.fromarray(img)
    image = preprocess(image).unsqueeze(0)

    with torch.no_grad():
        feat = model.encode_image(image)

    feat = feat.cpu().numpy()[0]
    return feat
