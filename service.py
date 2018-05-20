import os
import gzip
import io
import boto3
import json
import uuid
import datetime
from botocore.vendored import requests


def handler(event, context):
    """
    Iterate over an sqs queue and write events to a queue
    """
    BUCKET = os.environ.get('BUCKET', None)
    SQS_URL = os.environ.get('SQS_URL', None)
    if not BUCKET or not SQS_URL:
        return 'BUCKET and SQS_URL must be provided'

    # We will reinvoke the lambda when the remaining time falls bellow a
    # certain fraction of the initial time
    start_time = context.get_remaining_time_in_millis()

    sqs = boto3.resource('sqs', region_name='us-east-1')
    queue = sqs.Queue(SQS_URL)

    # If this isn't a re-invocation
    invoked = event.get('invoked', 1)
    if invoked == 1:
        # Send slack notif
        attachments = [
            { "fallback": "I'm about to run daily data event log compaction!\n:rocket: Here we gooooo!!!!",
              "text": "I'm about to run daily data event log compaction!\n:rocket: Here we gooooo!!!!",
              "color": "#005e99"
            }
        ]
        send_slack(attachments=attachments)

    messages = {}
    empty_batches = 0

    while empty_batches < 3:
        # Running out of time
        if context.get_remaining_time_in_millis() < start_time/2:
            # Upload, then re-invoke to continue processing
            taken = save_messages(messages)
            attachments = [
                { "fallback": ":hourglass: There's still events to process, but no time left!",
                  "text": ":hourglass: There's still events to process, but no time left!",
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
                },
                { "fallback": ":clock: Took {}s to upload log file".format(taken),
                  "text": ":clock: Took {}s to upload log file".format(taken),
                  "color": "warning"
                },
                { "fallback": ":deploying_dev: I'm going back for more!",
                  "text": ":deploying_dev: I'm going back for more!",
                  "color": "warning"
                }
            ]
            send_slack(attachments=attachments)
            # Re-invoke
            lam = boto3.client('lambda', region_name='us-east-1')
            response = lam.invoke(
                FunctionName=context.function_name,
                InvocationType='Event',
                Payload=str.encode(json.dumps({'invoked': invoked+1})),
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
        taken = save_messages(messages)
        attachments = [
            { "fields": [
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
              "color": "warning"
            },
            { "fallback": ":clock: Took {}s to upload log file".format(taken),
              "text": ":clock: Took {}s to upload log file".format(taken),
              "color": "warning"
            },
            { "fallback": ":white_check_mark: Finished storing the daily logs!",
              "text": ":white_check_mark: Finished storing the daily logs!",
              "color": "good"
            }
        ]
        send_slack(attachments=attachments)


def save_messages(messages):
    """
    Compress and upload messages
    """
    t0 = time.time()
    BUCKET = os.environ.get('BUCKET', None)
    s3 = boto3.client("s3", region_name='us-east-1')

    out = b'\n'.join(messages.values())
    # Save to a file with current timestamp
    now = datetime.datetime.utcnow()
    folder = now.strftime('%Y%m%d')
    suffix = str(uuid.uuid4())[:8]
    key = 'daily/{}/{}_{}.txt'.format(folder, now.strftime('%s'), suffix)
    #resp = s3.put_object(Body=gzip.compress(out), Bucket=BUCKET, Key=key)
    resp = s3.put_object(Body=out, Bucket=BUCKET, Key=key)
    t1 = time.time()
    return t1 - t0


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
