# dataset_metric.py
import pickle
import torch
from torch.utils.data import Dataset
import torchvision.transforms as T
import numpy as np
import cv2


class MetricCardDataset(Dataset):
    def __init__(self, pkl_path, image_size=256):
        with open(pkl_path, "rb") as f:
            self.cards = pickle.load(f)

        self.samples = []
        for label, card in enumerate(self.cards):
            for img in card["images"]:
                self.samples.append((img, label))

        self.transform = T.Compose([
            T.ToPILImage(),
            T.Resize((image_size, image_size)),
            T.ToTensor(),
            T.Normalize(
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            )
        ])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img, label = self.samples[idx]
        img = self.transform(img)
        return img, label

def extract_metric_feature(model, img_rgb, size=320):
    img = cv2.resize(img_rgb, (size, size))
    img = torch.from_numpy(img).permute(2, 0, 1).float() / 255.0

    mean = torch.tensor([0.485, 0.456, 0.406])[:, None, None]
    std  = torch.tensor([0.229, 0.224, 0.225])[:, None, None]
    img = (img - mean) / std

    img = img.unsqueeze(0)

    with torch.no_grad():
        feat = model(img).cpu().numpy()[0]

    return feat
