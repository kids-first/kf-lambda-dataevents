import os
import gzip
import io
import boto3
import json
import time
from botocore.vendored import requests



WAIT_TIME = 6


def handler(event, context):
    """
    Iterate over an sqs queue and write events to a queue
    """
    BUCKET = os.environ.get('BUCKET', None)
    SQS_URL = os.environ.get('SQS_URL', None)
    if not BUCKET or not SQS_URL:
        return 'BUCKET and SQS_URL must be provided'

    sqs = boto3.resource('sqs', region_name='us-east-1')
    queue = sqs.Queue(SQS_URL)

    # If this isn't a re-invocation
    invoked = event.get('invoked', 1)
    if invoked == 1:
        # Send slack notif
        attachments = [
            { "fallback": "I'm about to run daily data event log compaction!\nHere we gooooo!!!!",
              "text": "I'm about to run daily data event log compaction!\nHere we gooooo!!!!",
              "color": "#005e99"
            }
        ]
        send_slack(attachments=attachments)

    messages = {}
    empty_batches = 0

    batch = [None]
    while empty_batches < 3 and len(batch) > 0:
        # Running out of time
        if context.get_remaining_time_in_millis() < 5000:
            # Upload, then re-invoke to continue processing
            save_messages(messages)
            attachments = [
                { "fallback": "There's still events to process, but no time left! Re-invoking...",
                  "text": "There's still events to process, but no time left! Re-invoking...",
                  "fields": [
                      {
                          "title": "Events Saved",
                          "value": len(messages),
                          "short": True
                      },
                      {
                          "title": "Function Calls (so far)",
                          "value": invoked,
                          "short": True
                      }
                  ],
                  "color": "warning"
                }
            ]
            send_slack(attachments=attachments)
            # Re-invoke
            lam = boto3.client('lambda', region_name='us-east-1')
            response = lam.invoke(
                FunctionName=context.function_name,
                InvocationType='Event',
                Payload=str.encode(json.dumps({'invoked': invoked})),
            )
            break
        # Get the next batch of messages
        batch = queue.receive_messages(MaxNumberOfMessages=10,
                                       WaitTimeSeconds=1)

        if len(batch) == 0:
            empty_batches += 1
            continue

        # Iterate messages
        for message in batch:
            m = json.loads(message.body)
            messages[message.message_id] = m['Message'].replace("'", '"').encode()
            resp = message.delete()
    else:
        save_messages(messages)
        attachments = [
            { "fallback": "Finished storing the daily logs",
              "text": "Finished storing the daily logs",
              "fields": [
                  {
                      "title": "Events Saved",
                      "value": len(messages),
                      "short": True
                  },
                  {
                      "title": "Function Calls",
                      "value": invoked,
                      "short": True
                  }
              ],
              "color": "good"
            }
        ]
        send_slack(attachments=attachments)


def save_messages(messages):
    """
    Compress and upload messages
    """
    BUCKET = os.environ.get('BUCKET', None)
    s3 = boto3.client("s3", region_name='us-east-1')

    out = b'\n'.join(messages.values())
    # Save to a file with current timestamp
    resp = s3.put_object(Body=gzip.compress(out),
                         Bucket=BUCKET,             
                         Key='daily/{}.gz'.format(int(time.time())))


def send_slack(msg=None, attachments=None):
    """
    Sends a slack notification
    """
    SLACK_TOKEN = os.environ.get('SLACK_SECRET', None)
    SLACK_CHANNELS = os.environ.get('SLACK_CHANNEL', '').split(',')
    SLACK_CHANNELS = [c.replace('#','').replace('@','') for c in SLACK_CHANNELS]
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
