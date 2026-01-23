# model_metric.py
import timm
import torch.nn as nn
import torch.nn.functional as F

class ConvNeXtEmbed(nn.Module):
    def __init__(self, embed_dim=128):
        super().__init__()

        self.backbone = timm.create_model(
            "convnext_tiny",
            pretrained=True,
            num_classes=0
        )

        self.head = nn.Sequential(
            nn.Linear(768, 256),
            nn.BatchNorm1d(256),
            nn.GELU(),
            nn.Linear(256, embed_dim),
        )

    def forward(self, x):
        z = self.backbone(x)
        z = self.head(z)
        z = F.normalize(z, dim=1)
        return z
