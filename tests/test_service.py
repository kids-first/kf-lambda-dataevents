import io
import os
import boto3
import gzip
import json
import pytest
from moto import mock_s3, mock_sqs, mock_lambda
from mock import MagicMock, patch
import service

BUCKET = 'kf-events-us-east-1-dev-dataservice-dataevents'
KEY = 'daily/log.txt.gz'
QUEUE = 'kf-dataevents-sqs'


class Context:
    def __init__(self, remaining=20000):
        self.remaining = remaining
        self.function_name = 'kf-dataevents'

    def get_remaining_time_in_millis(self):
        self.remaining -= 500
        return self.remaining

@pytest.fixture
def obj():
    @mock_s3
    def with_obj():
        """ Create a harmonized file and its source file """
        s3 = boto3.client('s3', region_name='us-east-1')
        b = s3.create_bucket(Bucket=BUCKET)
        return s3
    return with_obj


@pytest.fixture()
def queue():
    @mock_sqs
    def with_sqs():
        client = boto3.client('sqs', region_name='us-east-1')
        response = client.create_queue(QueueName=QUEUE)
        url = response['QueueUrl']
        os.environ['SQS_URL'] = url
        return url
    return with_sqs


@pytest.fixture
def req():
    req_patch = patch('service.requests')
    req_mock = req_patch.start()
    yield req_mock
    req_mock.stop()


@pytest.fixture
def env():
    os.environ['BUCKET'] = BUCKET
    os.environ['SLACK_SECRET'] = 'abc'
    os.environ['SLACK_CHANNELS'] = 'chat'


@mock_sqs
@pytest.fixture
def messages(queue):
    queue_url = queue()

    msg = []
    with open('tests/messages.json') as f:
        for l in f:
            msg.append(l)

    for m in msg:
        sqs = boto3.client('sqs', region_name='us-east-1')
        # Send test message to queue
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=m
        )
    return msg


@mock_lambda
@mock_s3
def test_upload(obj, messages, req, env):
    """
    Test that compressed log file is created
    """
    s3 = obj()
    
    service.handler({}, Context(6000))
    
    assert len(s3.list_objects(Bucket=BUCKET)['Contents']) == 1

    stream = io.BytesIO()
    KEY = s3.list_objects(Bucket=BUCKET)['Contents'][0]['Key']
    ob = s3.get_object(Bucket=BUCKET, Key=KEY)
    dat = gzip.decompress(ob['Body'].read()).decode()

    for i, l in enumerate(dat.split('\n')):
        assert json.loads(messages[i])['Message'].replace("'", '"') == l
        message = json.loads(l)

        assert 'path' in message
        assert 'method' in message
        assert 'api_version' in message
        assert 'api_commit' in message
        assert 'data' in message

    assert req.post.call_count == 2


@mock_lambda
@mock_s3
def test_delete(obj, messages, queue, req, env):
    """
    Test that messages are deleted after being written
    """
    s3 = obj()
    queue_url = queue()
    
    service.handler({}, Context(6000))
    sqs = boto3.resource('sqs', region_name='us-east-1')
    queue = sqs.Queue(queue_url)
    
    batch = queue.receive_messages(MaxNumberOfMessages=10,
                                   WaitTimeSeconds=0)
    assert len(batch) == 0
    assert req.post.call_count == 2


@mock_lambda
@mock_s3
def test_reinvoke(obj, messages, queue, req, env):
    """
    Test that messages are deleted after being written
    """
    s3 = obj()
    queue_url = queue()
    patch_lam = patch('boto3.client')
    mock_lam = patch_lam.start()
    
    service.handler({}, Context(200))
    sqs = boto3.resource('sqs', region_name='us-east-1')
    queue = sqs.Queue(queue_url)

    assert mock_lam().invoke.call_count == 1
    assert mock_lam().put_object.call_count == 1
    assert req.post.call_count == 2

    mock_lam.stop()
