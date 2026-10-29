"""Optional billing delivery and disposable recovery infrastructure."""
import json
from pathlib import Path

from build_template import attr, ref, sub


def resource(kind, properties, why, must=(), **extra):
    return {"Type": kind, "Properties": properties,
            "Metadata": {"com.aws.cloudformation.Context": {"why": why, "must": list(must)}},
            **extra}


def base(description):
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": description,
            "Metadata": {"AWSToolsMetrics": {"AWSAgentToolkit": "aws-cloudformation@3"}}}


def billing():
    template = base("Private versioned Legacy CUR delivery for Workbench's CSV collector; billing stays in the owning account.")
    condition = {"StringEquals": {
        "aws:SourceAccount": ref("AWS::AccountId"),
        # CUR documents this literal source ARN for its delivery service.
        "aws:SourceArn": sub("arn:${AWS::Partition}:cur:us-east-1:${AWS::AccountId}:definition/*"),
    }}
    template["Resources"] = {
        "BillingBucket": resource("AWS::S3::Bucket", {
            "PublicAccessBlockConfiguration": {key: True for key in
                ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")},
            "BucketEncryption": {"ServerSideEncryptionConfiguration": [
                {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
            "VersioningConfiguration": {"Status": "Enabled"},
        }, "Retain private billing history independently of report scheduling.",
            ["Never publish billing objects; encrypt and block all public access."],
            DeletionPolicy="Retain", UpdateReplacePolicy="Retain"),
        "BillingPolicy": resource("AWS::S3::BucketPolicy", {
            "Bucket": ref("BillingBucket"),
            "PolicyDocument": {"Version": "2012-10-17", "Statement": [
                {"Effect": "Deny", "Principal": "*", "Action": "s3:*",
                 "Resource": [attr("BillingBucket", "Arn"), sub("${BillingBucket.Arn}/*")],
                 "Condition": {"Bool": {"aws:SecureTransport": "false"}}},
                {"Effect": "Allow", "Principal": {"Service": "billingreports.amazonaws.com"},
                 "Action": ["s3:GetBucketAcl", "s3:GetBucketPolicy"],
                 "Resource": attr("BillingBucket", "Arn"), "Condition": condition},
                {"Effect": "Allow", "Principal": {"Service": "billingreports.amazonaws.com"},
                 # CUR also validates delivery at the bucket root. The bucket is
                 # dedicated to this export; account/service conditions remain.
                 "Action": "s3:PutObject", "Resource": sub("${BillingBucket.Arn}/*"),
                 "Condition": condition},
            ]},
        }, "Allow this account's CUR delivery service and require TLS.",
            ["Keep the documented CUR SourceArn and SourceAccount restrictions."]),
        "Report": resource("AWS::CUR::ReportDefinition", {
            "ReportName": ref("AWS::StackName"), "TimeUnit": "HOURLY",
            "Format": "textORcsv", "Compression": "GZIP", "AdditionalSchemaElements": [],
            "S3Bucket": ref("BillingBucket"), "S3Prefix": "exports",
            "S3Region": ref("AWS::Region"), "RefreshClosedReports": True,
            "ReportVersioning": "CREATE_NEW_REPORT",
        }, "Use the collector's validated CSV assembly contract; delivery is asynchronous.",
            ["Do not replace with CUR 2.0 or overwrite mode without a validated adapter."],
            DependsOn="BillingPolicy"),
    }
    template["Outputs"] = {
        "Bucket": {"Value": ref("BillingBucket"), "Description": "Private export destination"},
        "ReportName": {"Value": ref("AWS::StackName"), "Description": "Monthly report prefix component"},
    }
    return template


def recovery():
    template = base("Disposable SSM-only Workbench recovery host; original backups are read-only and the running host is untouched.")
    template["Parameters"] = {
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "SubnetId": {"Type": "AWS::EC2::Subnet::Id"},
        "ImageId": {"Type": "AWS::EC2::Image::Id"},
        "BackupBucket": {"Type": "String", "AllowedPattern": "[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"},
        "DrillPrefix": {"Type": "String", "AllowedPattern": "bootstrap/recovery-[a-z0-9-]+/"},
    }
    bootstrap = """#!/bin/bash
set -euo pipefail
# Terminate the disposable host even if the operator loses its session.
systemd-run --unit=workbench-recovery-deadline --on-active=2h /sbin/shutdown -h now
dnf install -y docker python3
systemctl enable --now docker
useradd --create-home --groups docker workbench
install -d -m 700 -o workbench -g workbench /opt/workbench
install -d -m 755 /usr/local/lib/docker/cli-plugins
cd /usr/local/lib/docker/cli-plugins
curl --fail --location --retry 3 https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64 -o docker-compose
printf 'dba9d98e1ba5bfe11d88c99b9bd32fc4a0624a30fafe68eea34d61a3e42fd372  docker-compose\\n' | sha256sum --check --status
curl --fail --location --retry 3 https://github.com/docker/buildx/releases/download/v0.38.1/buildx-v0.38.1.linux-amd64 -o docker-buildx
printf 'e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4  docker-buildx\\n' | sha256sum --check --status
chmod 755 docker-compose docker-buildx
touch /opt/workbench/bootstrap-ready
chown workbench:workbench /opt/workbench/bootstrap-ready
"""
    template["Resources"] = {
        "RecoveryRole": resource("AWS::IAM::Role", {
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole"}]},
            "ManagedPolicyArns": [sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore")],
            "Policies": [{"PolicyName": "recovery-objects", "PolicyDocument": {
                "Version": "2012-10-17", "Statement": [
                    {"Effect": "Allow", "Action": "s3:GetObject",
                     "Resource": [sub("arn:${AWS::Partition}:s3:::${BackupBucket}/backups/*"),
                                  sub("arn:${AWS::Partition}:s3:::${BackupBucket}/${DrillPrefix}*")]},
                    {"Effect": "Allow", "Action": "s3:PutObject",
                     "Resource": sub("arn:${AWS::Partition}:s3:::${BackupBucket}/${DrillPrefix}evidence/*")},
                ]}}],
        }, "Read backups and this drill's bootstrap; write receipts only.",
            ["No backup writes, metrics publishing, billing access or embedded AWS credentials."]),
        "RecoveryProfile": resource("AWS::IAM::InstanceProfile", {
            "Roles": [ref("RecoveryRole")]}, "Supply temporary credentials to host automation."),
        "RecoverySecurityGroup": resource("AWS::EC2::SecurityGroup", {
            "GroupDescription": "SSM-only recovery drill; no ingress",
            "VpcId": ref("VpcId"), "SecurityGroupIngress": [],
        }, "Outbound management and dependency downloads; no public listener or SSH.",
            ["Never reuse or widen the original host security group."]),
        "RecoveryHost": resource("AWS::EC2::Instance", {
            "ImageId": ref("ImageId"), "InstanceType": "t3a.large",
            "SubnetId": ref("SubnetId"), "SecurityGroupIds": [ref("RecoverySecurityGroup")],
            "IamInstanceProfile": ref("RecoveryProfile"),
            "CreditSpecification": {"CPUCredits": "standard"},
            "InstanceInitiatedShutdownBehavior": "terminate",
            "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
            "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {
                "VolumeSize": 60, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
            "UserData": {"Fn::Base64": bootstrap},
            "Tags": [{"Key": "Name", "Value": sub("${AWS::StackName}-disposable")},
                     {"Key": "Workload", "Value": "workbench-recovery-drill"}],
        }, "Rebuild on independent compute and disks; automatically terminate after two hours.",
            ["Restore only into new volumes; no original timers or public DNS changes.",
             "Retain receipts off-host before deleting the disposable stack."],
            DeletionPolicy="Delete", UpdateReplacePolicy="Delete"),
    }
    template["Outputs"] = {
        "InstanceId": {"Value": ref("RecoveryHost"), "Description": "Disposable SSM target"},
    }
    return template


if __name__ == "__main__":
    root = Path(__file__).parent
    for name, create in (("billing-export.json", billing), ("recovery-drill.json", recovery)):
        (root/name).write_text(json.dumps(create(), indent=2) + "\n")
