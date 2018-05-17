import os
import boto3
import json
from botocore.vendored import requests


s3 = boto3.client("s3", region_name='us-east-1')


SQS_URL = os.environ.get('SQS_URL', None)
BUCKET = os.environ.get('BUCKET', None)
SLACK_TOKEN = os.environ.get('SLACK_SECRET', None)
SLACK_CHANNELS = os.environ.get('SLACK_CHANNEL', '').split(',')
SLACK_CHANNELS = [c.replace('#','').replace('@','') for c in SLACK_CHANNELS]


def handler(event, context):
    """
    Iterate over an sqs queue and write events to a queue
    """
    if not BUCKET or not SQS_URL:
        return 'BUCKET and SQS_URL must be provided'

    sqs = boto3.resource('sqs', region_name='us-east-1')
    queue = sqs.Queue(SQS_URL)

    # If this isn't a re-invocation
    if 'key' not in event:
        # Send slack notif
        attachments = [
            { "fallback": "I'm about to run daily data event log compaction!",
              "text": "I'm about to run daily data event log compaction!",
              "color": "#005e99"
            }
        ]
        send_slack(attachments=attachments)

    for message in queue.receive_messages(MaxNumberOfMessages=10, WaitTimeSeconds=4):
        # process message body
        body = json.loads(message.body)
        print('check')
        print(body['MessageId'], json.loads(body['Message'])['data']['results']['kf_id'])


def send_slack(msg=None, attachments=None):
    """
    Sends a slack notification
    """
    if SLACK_TOKEN is not None:
        for channel in SLACK_CHANNELS:
            message = {
                'username': 'Data Event Compactor Bot',
                'icon_emoji': ':card_file_box:',
                'channel': channel
            }
            if msg:
                message['text'] = msg
            if attachments:
                message['attachments'] = attachments

            resp = requests.post('https://slack.com/api/chat.postMessage',
                headers={'Authorization': 'Bearer '+SLACK_TOKEN},
                json=message)
