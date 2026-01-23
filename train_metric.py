# train_metric.py
from pathlib import Path
import torch
from torch.utils.data import DataLoader
import torch.nn as nn
import torch.optim as optim

from dataset_metric import MetricCardDataset
from model_metric import ConvNeXtEmbed
from arcface import ArcFace
from datetime import datetime
import time


def train_metric(csv_path: Path, epochs=30, batch_size=32, log_fn=print):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    pkl_path = csv_path.parent / "deck_metric.pkl"
    dataset = MetricCardDataset(pkl_path, image_size=320)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=2,
        drop_last=True
    )

    num_classes = len(dataset.cards)

    model = ConvNeXtEmbed(embed_dim=256).to(device)
    arcface = ArcFace(
        in_features=256,
        out_features=num_classes,
        s=40.0,
        m=0.4
    ).to(device)

    for name, p in model.backbone.named_parameters():
        if "stages.3" in name:  # final stage
            p.requires_grad = True

    optimizer = optim.AdamW([
        {"params": model.head.parameters(), "lr": 5e-4},
        {"params": arcface.parameters(), "lr": 5e-4},
        {"params": model.backbone.stages[3].parameters(), "lr": 1e-5},
    ])

    criterion = nn.CrossEntropyLoss()

    log_fn(f"[INFO] classes={num_classes}, samples={len(dataset)}")
    start_time = time.time()
    now = datetime.now().strftime("%H:%M:%S")
    log_fn(f"[INFO] [{now}] Start Metric training for Total {epochs} epochs")
    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0

        for imgs, labels in loader:
            imgs = imgs.to(device)
            labels = labels.to(device)

            emb = model(imgs)
            logits = arcface(emb, labels)
            loss = criterion(logits, labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        avg_loss = total_loss / len(loader)
        now = datetime.now().strftime("%H:%M:%S")
        elapsed = time.time() - start_time
        log_fn(
            f"[INFO] [{now}] "
            f"[Epoch {epoch:03d}] "
            f"loss={avg_loss:.4f} "
            f"total elapsed time={elapsed:.1f}s"
        )

    # save embedding model
    out = csv_path.parent / "metric_model.pth"
    torch.save(model.state_dict(), out)
    log_fn(f"[OK] model saved: {out}")
