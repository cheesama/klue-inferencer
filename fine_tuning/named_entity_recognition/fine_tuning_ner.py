from datasets import load_dataset, load_metric
from transformers import AutoTokenizer, AutoModelForMaskedLM, TrainingArguments, Trainer
from transformers import AutoModelForTokenClassification
from transformers import AdamW, get_scheduler
from torch.utils.data import Dataset, DataLoader
from tqdm.auto import tqdm

import torch
import torch.nn as nn
import torch.nn.functional as F
import pytorch_lightning as pl
import argparse
import multiprocessing


class NERDataset(Dataset):
    def __init__(self, tokenizer, data_list, max_token_length=256, o_tag_id=12):
        super().__init__()
        self.tokenizer = tokenizer
        self.max_token_length = max_token_length
        self.o_tag_id = o_tag_id  # based on KLUE NER dataset

        token_ids_arr = map(
            self.tokenizer.encode, ["".join(item["tokens"]) for item in data_list]
        )
        labels_arr = [item["ner_tags"] for item in data_list]
        self.data_list = list(zip(token_ids_arr, labels_arr))

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        tokens = self.data_list[idx][0]
        if len(tokens) < self.max_token_length:
            tokens += [self.tokenizer.pad_token_id] * (
                self.max_token_length - len(tokens)
            )

        labels = self.data_list[idx][1]
        if len(labels) < self.max_token_length:
            labels += [self.o_tag_id] * (self.max_token_length - len(labels))

        tokens, labels = (
            torch.LongTensor(tokens[: self.max_token_length]),
            torch.LongTensor(labels[: self.max_token_length]),
        )
        return tokens, labels


class NERModel(pl.LightningModule):
    def __init__(
        self, backbone_size="small", lr=5e-5, max_token_length=256, entity_class_num=13
    ):
        super().__init__()

        self.loss_func = nn.CrossEntropyLoss()
        self.lr = lr
        self.max_token_length = max_token_length
        self.entity_class_num = entity_class_num  # based on KLUE NER dataset

        # model & tokenizer prepare
        self.backbone_size = backbone_size
        if self.backbone_size == "small":
            self.tokenizer = AutoTokenizer.from_pretrained("klue/roberta-small")
            self.model = AutoModelForTokenClassification.from_pretrained(
                "klue/roberta-small"
            )
        elif self.backbone_size == "base":
            self.tokenizer = AutoTokenizer.from_pretrained("klue/roberta-base")
            self.model = AutoModelForTokenClassification.from_pretrained(
                "klue/roberta-base"
            )
        elif self.backbone_size == "large":
            self.tokenizer = AutoTokenizer.from_pretrained("klue/roberta-large")
            self.model = AutoModelForTokenClassification.from_pretrained(
                "klue/roberta-large"
            )
        else:
            raise ValueError("backbone size should be one of [small, base, large]")

        self.model.classifier = nn.Linear(
            self.model.classifier.in_features, self.entity_class_num
        )
        nn.init.xavier_uniform_(self.model.classifier.weight)

        self.save_hyperparameters()

    def forward(self, x):
        pred = self.model(x).logits
        return pred

    def configure_optimizers(self):
        optim = torch.optim.Adam(self.parameters(), lr=self.lr)
        return optim

    def prepare_token_ids(self, input_data):
        if type(input_data) == list:
            input_data = "".join(input_data)

        tokens = self.tokenizer.encode(input_data)
        if len(tokens) < self.max_token_length:
            tokens += [self.tokenizer.pad_token_id] * (
                self.max_token_length - len(tokens)
            )

        return tokens[: self.max_token_length]

    def training_step(self, batch, batch_idx):
        self.model.train()
        token_ids, entity_ids = batch
        pred_ids = self.model(token_ids).logits

        loss = self.loss_func(pred_ids.transpose(2, 1), entity_ids)
        self.log("train/loss", loss, prog_bar=True)

        return loss

    def validation_step(self, batch, batch_idx):
        self.model.eval()

        with torch.no_grad():
            token_ids, entity_ids = batch
            pred_ids = self.model(token_ids).logits

            loss = self.loss_func(pred_ids.transpose(2, 1), entity_ids)
            self.log("val/loss", loss, prog_bar=True)

            return loss


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", default=5e-5)
    parser.add_argument("--epochs", default=10)
    parser.add_argument("--batch_size", default=2)
    args = parser.parse_args()

    # model preparation
    model = NERModel(lr=args.lr)

    # data preparation
    ner_dataset = load_dataset("klue", "ner")
    train_data = ner_dataset["train"]
    valid_data = ner_dataset["validation"]

    train_dataset = NERDataset(model.tokenizer, train_data)
    valid_dataset = NERDataset(model.tokenizer, valid_data)

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        num_workers=multiprocessing.cpu_count(),
        shuffle=True,
    )
    valid_loader = DataLoader(
        valid_dataset,
        batch_size=args.batch_size,
        num_workers=multiprocessing.cpu_count(),
    )

    trainer = pl.Trainer(
        gpus=torch.cuda.device_count(),
        progress_bar_refresh_rate=1,
        accelerator="ddp",
        max_epochs=args.epochs,
    )

    trainer.fit(model, train_loader, valid_loader)
