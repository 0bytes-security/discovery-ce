import boto3
from botocore.client import Config as BotoConfig

from discovery.core import config


def get_s3_client():
    s3_config = config.s3_config
    return boto3.resource(
        "s3",
        region_name=s3_config.region_name,
        endpoint_url=s3_config.endpoint_url,
        aws_access_key_id=s3_config.access_key_id,
        aws_secret_access_key=s3_config.secret_access_key,
        config=BotoConfig(
            signature_version="s3v4",
            connect_timeout=5,
            retries={"max_attempts": 3},
        ),
        verify=s3_config.verify_ssl,
    )


BUCKET_NAME = config.s3_config.bucket_name
