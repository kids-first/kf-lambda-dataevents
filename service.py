import os
import boto3
import json
from botocore.vendored import requests


s3 = boto3.client("s3")


def handler(event, context):
    """
    Iterate over an sqs queue and write events to a queue
    """
    pass
