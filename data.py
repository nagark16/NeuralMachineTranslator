
import os
import random
import re

import numpy as np

import config



def basic_tokenizer(line, normalize_digits=True):
    """ A basic tokenizer to tokenize text into tokens.
    Feel free to change this to suit your need. """
    print()
    line = re.sub('<u>', '', line)
    line = re.sub('</u>', '', line)
    line = re.sub('\[', '', line)
    line = re.sub('\]', '', line)
    words = []
    _WORD_SPLIT = re.compile("([.,!?\"'-<>:;)(])")
    _DIGIT_RE = re.compile(r"\d")
    for fragment in line.strip().lower().split():
        for token in re.split(_WORD_SPLIT, fragment):
            if not token:
                continue
            if normalize_digits:
                token = re.sub(_DIGIT_RE, '#', token)
            words.append(token)
    return words

def build_vocab(filename, normalize_digits=True):
    in_path = os.path.join(config.PROCESSED_PATH, filename)
    out_path = os.path.join(config.PROCESSED_PATH, 'vocab.{}'.format(filename[-3:]))

    vocab = {}
    with open(in_path, 'r') as f:
        for line in f.readlines():
            for token in basic_tokenizer(line):
                if not token in vocab:
                    vocab[token] = 0
                vocab[token] += 1

    sorted_vocab = sorted(vocab, key=vocab.get, reverse=True)
    with open(out_path, 'w') as f:
        f.write('<pad>' + '\n')
        f.write('<unk>' + '\n')
        f.write('<s>' + '\n')
        f.write('<\s>' + '\n') 
        index = 4
        for word in sorted_vocab:
            if vocab[word] < config.THRESHOLD:
                break
            f.write(word + '\n')
            index += 1
        with open('config.py', 'a') as cf:
            if filename[-3:] == 'enc':
                cf.write('ENC_VOCAB = ' + str(index) + '\n')
            else:
                cf.write('DEC_VOCAB = ' + str(index) + '\n')

def load_vocab(vocab_path):
    with open(vocab_path, 'r',encoding="utf8") as f:
        words = f.read().splitlines()
    return words, {words[i]: i for i in range(len(words))}

def sentence2id(vocab, line):
    return [vocab.get(token, vocab['<unk>']) for token in basic_tokenizer(line)]

def token2id(data, mode):
    """ Convert all the tokens in the data into their corresponding
    index in the vocabulary. """
    vocab_path = 'vocab.' + mode
    in_path = data + '.' + mode
    out_path = data + '_ids.' + mode

    _, vocab = load_vocab(os.path.join(config.PROCESSED_PATH, vocab_path))
    in_file = open(os.path.join(config.PROCESSED_PATH, in_path), 'r')
    out_file = open(os.path.join(config.PROCESSED_PATH, out_path), 'w')
    
    lines = in_file.read().splitlines()
    for line in lines:
        if mode == 'dec': # we only care about '<s>' and </s> in encoder
            ids = [vocab['<s>']]
        else:
            ids = []
        ids.extend(sentence2id(vocab, line))
        # ids.extend([vocab.get(token, vocab['<unk>']) for token in basic_tokenizer(line)])
        if mode == 'dec':
            ids.append(vocab['<\s>'])
        out_file.write(' '.join(str(id_) for id_ in ids) + '\n')

def make_dir(path):
    """ Create a directory if there isn't one already. """
    try:
        os.mkdir(path)
    except OSError:
        pass

def process_data():
    print('Preparing data to be model-ready ...')
    build_vocab('train.enc')
    build_vocab('train.dec')
    token2id('train', 'enc')
    token2id('train', 'dec')
    token2id('test', 'enc')
    token2id('test', 'dec')

def load_data(enc_filename, dec_filename, max_training_size=None):
    encode_file = open(os.path.join(config.PROCESSED_PATH, enc_filename), 'r')
    decode_file = open(os.path.join(config.PROCESSED_PATH, dec_filename), 'r')
    encode, decode = encode_file.readline(), decode_file.readline()
    data_buckets = [[] for _ in config.BUCKETS]
    i = 0
    while encode and decode:
        if (i + 1) % 10000 == 0:
            print("Bucketing conversation number", i)
        encode_ids = [int(id_) for id_ in encode.split()]
        decode_ids = [int(id_) for id_ in decode.split()]
        for bucket_id, (encode_max_size, decode_max_size) in enumerate(config.BUCKETS):
            if len(encode_ids) <= encode_max_size and len(decode_ids) <= decode_max_size:
                data_buckets[bucket_id].append([encode_ids, decode_ids])
                break
        encode, decode = encode_file.readline(), decode_file.readline()
        i += 1
    return data_buckets

def load_test_data(filename, max_training_size=None):
    encode_file = os.path.join(config.PROCESSED_PATH, filename)
    data_buckets = [[] for _ in config.BUCKETS]
    data = []
    with open(encode_file, 'r',encoding='utf-8') as f:
        for line in f.readlines():
            data.append(line)
    return data

def _pad_input(input_, size):
    return input_ + [config.PAD_ID] * (size - len(input_))

def _reshape_batch(inputs, size, batch_size):
    """ Create batch-major inputs. Batch inputs are just re-indexed inputs
    """
    batch_inputs = []
    for length_id in range(size):
        batch_inputs.append(np.array([inputs[batch_id][length_id]
                                    for batch_id in range(batch_size)], dtype=np.int32))
    return batch_inputs


def get_batch(data_bucket, bucket_id, batch_size=1):
    """ Return one batch to feed into the model """
    # only pad to the max length of the bucket
    encoder_size, decoder_size = config.BUCKETS[bucket_id]
    encoder_inputs, decoder_inputs = [], []

    for _ in range(batch_size):
        encoder_input, decoder_input = random.choice(data_bucket)
        # pad both encoder and decoder, reverse the encoder
        temp = _pad_input(encoder_input, encoder_size)
        encoder_inputs.append(list(reversed(_pad_input(encoder_input, encoder_size))))
        decoder_inputs.append(_pad_input(decoder_input, decoder_size))

    # now we create batch-major vectors from the data selected above.
    batch_encoder_inputs = _reshape_batch(encoder_inputs, encoder_size, batch_size)
    batch_decoder_inputs = _reshape_batch(decoder_inputs, decoder_size, batch_size)

    # create decoder_masks to be 0 for decoders that are padding.
    batch_masks = []
    for length_id in range(decoder_size):
        batch_mask = np.ones(batch_size, dtype=np.float32)
        for batch_id in range(batch_size):
            # we set mask to 0 if the corresponding target is a PAD symbol.
            # the corresponding decoder is decoder_input shifted by 1 forward.
            if length_id < decoder_size - 1:
                target = decoder_inputs[batch_id][length_id + 1]
            if length_id == decoder_size - 1 or target == config.PAD_ID:
                batch_mask[batch_id] = 0.0
        batch_masks.append(batch_mask)
    return batch_encoder_inputs, batch_decoder_inputs, batch_masks

if __name__ == '__main__':
    process_data()