from datasets import load_dataset, load_metric
from transformers import TFAutoModelForSequenceClassification, AutoTokenizer
from transformers import AdamW, get_scheduler
from tensorflow import keras
from tensorflow.keras import layers

from tqdm.auto import tqdm

import argparse
import multiprocessing
import tensorflow as tf

def create_topic_dataset(tokenizer, max_seq_len=256, batch_size=8):
    topic_dataset = load_dataset('klue', 'ynat')
    train_dataset = topic_dataset['train']
    valid_dataset = topic_dataset['validation']

    train_features={'input_ids':[], 'label': []}
    for train_data in tqdm(train_dataset, desc='tokenizing train dataset ...'):
        tokens = tokenizer.encode(train_data['title'])
        if len(tokens) < max_seq_len:
            tokens += [tokenizer.pad_token_id] * (max_seq_len - len(tokens))
        tokens = tokens[:max_seq_len]
        train_features['input_ids'].append(tokens)
        train_features['label'].append(train_data['label'])

    valid_features={'input_ids':[], 'label': []}
    for valid_data in tqdm(valid_dataset, desc='tokenizing valid dataset ...'):
        tokens = tokenizer.encode(valid_data['title'])
        if len(tokens) < max_seq_len:
            tokens += [tokenizer.pad_token_id] * (max_seq_len - len(tokens))
        tokens = tokens[:max_seq_len]
        valid_features['input_ids'].append(tokens)
        valid_features['label'].append(valid_data['label'])

    train_tf_dataset = tf.data.Dataset.from_tensor_slices((train_features, train_features['label'])).shuffle(len(train_features)).batch(batch_size)
    valid_tf_dataset = tf.data.Dataset.from_tensor_slices((valid_features, valid_features['label'])).batch(batch_size)

    return train_tf_dataset, valid_tf_dataset

def create_topic_model(lr=5e-5, topic_class_num=7, class_dict=None):
    # model & tokenizer prepare
    encoder = TFAutoModelForSequenceClassification.from_pretrained("monologg/koelectra-base-discriminator", num_labels=topic_class_num)

    loss_func = keras.losses.SparseCategoricalCrossentropy(from_logits=True)
    optimizer = keras.optimizers.Adam(lr=lr)
    metrics_func = tf.metrics.SparseCategoricalAccuracy()
    encoder.compile(optimizer=optimizer, loss=loss_func, metrics=metrics_func)

    return encoder

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", default=1e-4, type=float)
    parser.add_argument("--epochs", default=10, type=int)
    # parser.add_argument("--batch_size", default=64, type=int) # small model, 12GB GPU based
    parser.add_argument("--batch_size", default=2, type=int)
    args = parser.parse_args()

    # model preparation
    model = create_topic_model(lr=args.lr)

    tokenizer = AutoTokenizer.from_pretrained("monologg/koelectra-base-discriminator")

    # data preparation
    train_dataset, valid_dataset = create_topic_dataset(tokenizer)

    model.fit(train_dataset, validation_data=valid_dataset, epochs=args.epochs)
