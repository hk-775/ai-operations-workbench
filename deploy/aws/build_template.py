"""Generate the company-neutral infrastructure for the opt-in hosted acceptance test."""
import json
from pathlib import Path


def ref(name):
    return {"Ref": name}


def attr(name, key):
    return {"Fn::GetAtt": [name, key]}


def sub(value):
    return {"Fn::Sub": value}


def template():
    resources = {}

    def add(name, kind, properties, why, must=(), **extra):
        resources[name] = {
            "Type": kind,
            "Metadata": {"com.aws.cloudformation.Context": {"why": why, "must": list(must)}},
            "Properties": properties,
            **extra,
        }

    add("Storage", "AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {k: True for k in (
            "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")},
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
        "VersioningConfiguration": {"Status": "Enabled"},
        "LifecycleConfiguration": {"Rules": [
            {"Id": "backups", "Status": "Enabled", "Prefix": "backups/",
             "ExpirationInDays": 30, "NoncurrentVersionExpiration": {"NoncurrentDays": 30}},
            {"Id": "private-bootstrap", "Status": "Enabled", "Prefix": "bootstrap/",
             "ExpirationInDays": 1, "NoncurrentVersionExpiration": {"NoncurrentDays": 1}},
        ]},
    }, "Off-host recovery and private bootstrap; no public artifacts.", [
        "Block public access, encrypt, and retain independently of server replacement.",
        "Never put bootstrap objects or backup contents in logs."],
        DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
    add("StoragePolicy", "AWS::S3::BucketPolicy", {
        "Bucket": ref("Storage"), "PolicyDocument": {"Version": "2012-10-17", "Statement": [{
            "Effect": "Deny", "Principal": "*", "Action": "s3:*",
            "Resource": [attr("Storage", "Arn"), sub("${Storage.Arn}/*")],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }]}}, "Require TLS for artifact and backup transfers.")
    add("ServerRole", "AWS::IAM::Role", {
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"}]},
        "ManagedPolicyArns": [sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore")],
        "Policies": [{"PolicyName": "workbench-storage-metrics", "PolicyDocument": {
            "Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                 "Resource": sub("${Storage.Arn}/*")},
                {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": attr("Storage", "Arn")},
                {"Effect": "Allow", "Action": "cloudwatch:PutMetricData", "Resource": "*",
                 "Condition": {"StringEquals": {"cloudwatch:namespace": "Workbench/HostedTest"}}},
            ]}}],
    }, "SSM management, this deployment's artifacts, and one metrics namespace.",
        ["No SSH or embedded AWS keys; application containers cannot access instance metadata."])
    add("ServerProfile", "AWS::IAM::InstanceProfile", {"Roles": [ref("ServerRole")]},
        "Give host automation temporary AWS credentials.")
    add("OriginSecurityGroup", "AWS::EC2::SecurityGroup", {
        "GroupDescription": "Workbench origin; only CloudFront can enter",
        "VpcId": ref("VpcId"),
        "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                                  "SourcePrefixListId": ref("CloudFrontPrefixListId")}],
    }, "Only the CloudFront origin network can reach the HTTP listener.",
        ["No public CIDR ingress and no inbound SSH."])
    user_data = """#!/bin/bash
set -euo pipefail
dnf install -y docker python3
systemctl enable --now docker
useradd --create-home --groups docker workbench
install -d -m 700 -o workbench -g workbench /opt/workbench
install -d -m 755 /usr/local/lib/docker/cli-plugins
curl --fail --location --retry 3 https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
cd /usr/local/lib/docker/cli-plugins
printf 'dba9d98e1ba5bfe11d88c99b9bd32fc4a0624a30fafe68eea34d61a3e42fd372  docker-compose\\n' | sha256sum --check --status
curl --fail --location --retry 3 https://github.com/docker/buildx/releases/download/v0.38.1/buildx-v0.38.1.linux-amd64 -o docker-buildx
printf 'e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4  docker-buildx\\n' | sha256sum --check --status
chmod 755 docker-compose docker-buildx
touch /opt/workbench/bootstrap-ready
chown workbench:workbench /opt/workbench/bootstrap-ready
"""
    add("Server", "AWS::EC2::Instance", {
        "ImageId": ref("ImageId"), "InstanceType": ref("InstanceType"),
        "SubnetId": ref("SubnetId"), "SecurityGroupIds": [ref("OriginSecurityGroup")],
        "IamInstanceProfile": ref("ServerProfile"),
        "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
        "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {
            "VolumeSize": 60, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": False}}],
        "UserData": {"Fn::Base64": user_data},
        "Tags": [{"Key": "Name", "Value": sub("${AWS::StackName}-host")},
                 {"Key": "Workload", "Value": "workbench-hosted-test"}],
    }, "Dedicated Docker host for two isolated test stacks; encrypted retained disk.",
        ["Fictional data only; preserve disk and off-host backups during replacement.",
         "Metadata hop limit 1 deliberately denies credentials to application containers."],
        DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
    add("PrivateOrigin", "AWS::CloudFront::VpcOrigin", {
        "VpcOriginEndpointConfig": {
            "Arn": sub("arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/${Server}"),
            "Name": sub("${AWS::StackName}-origin"), "HTTPPort": 80, "HTTPSPort": 443,
            "OriginProtocolPolicy": "http-only", "OriginSSLProtocols": ["TLSv1.2"],
        }},
        "CloudFront reaches the host over its private VPC network, avoiding a public HTTP origin.",
        ["Public viewers use HTTPS; internal VPC and Docker hops use HTTP."])
    add("WebAcl", "AWS::WAFv2::WebACL", {
        "Scope": "CLOUDFRONT", "DefaultAction": {"Allow": {}},
        "VisibilityConfig": {"SampledRequestsEnabled": False, "CloudWatchMetricsEnabled": True,
                             "MetricName": sub("${AWS::StackName}-web")},
        "Rules": [{"Name": "request-rate", "Priority": 1, "Action": {"Block": {}},
                   "Statement": {"RateBasedStatement": {"Limit": 1000, "AggregateKeyType": "IP"}},
                   "VisibilityConfig": {"SampledRequestsEnabled": False,
                                        "CloudWatchMetricsEnabled": True, "MetricName": "request-rate"}}],
    }, "Bound anonymous request volume without storing OIDC callback query strings.")
    for label in ("Demo", "Clean"):
        add(label+"Distribution", "AWS::CloudFront::Distribution", {
            "DistributionConfig": {
                "Enabled": True, "Comment": sub("${AWS::StackName}-"+label.lower()),
                "PriceClass": "PriceClass_100", "HttpVersion": "http2", "IPV6Enabled": True,
                "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
                "WebACLId": attr("WebAcl", "Arn"),
                "Origins": [{"Id": "workbench", "DomainName": attr("Server", "PrivateDnsName"),
                             "VpcOriginConfig": {"VpcOriginId": ref("PrivateOrigin")}}],
                "DefaultCacheBehavior": {
                    "TargetOriginId": "workbench", "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                    "CachedMethods": ["GET", "HEAD"], "Compress": True,
                    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                    "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
                },
                "CustomErrorResponses": [{"ErrorCode": code, "ErrorCachingMinTTL": 0}
                                         for code in (400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504)],
            }},
            "Separate HTTPS hostname and cookies for the "+label.lower()+" workspace.",
            ["Never cache authenticated responses or strip OIDC cookies and query parameters."])
    add("TestUsers", "AWS::Cognito::UserPool", {
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
        "MfaConfiguration": "OFF",
        "Policies": {"PasswordPolicy": {"MinimumLength": 16, "RequireUppercase": True,
                     "RequireLowercase": True, "RequireNumbers": True, "RequireSymbols": True,
                     "TemporaryPasswordValidityDays": 1}},
        "UserPoolTags": {"Workload": "workbench-hosted-test"},
    }, "Dedicated real OIDC provider. The user explicitly requested no MFA for this test.",
        ["Never present this password-only test as verified production MFA acceptance."],
        DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
    add("LoginDomain", "AWS::Cognito::UserPoolDomain", {
        "Domain": sub("${AWS::StackName}-${AWS::AccountId}"),
        "UserPoolId": ref("TestUsers"),
    }, "AWS-provided test sign-in address; no custom company domain needed.")
    for label in ("Demo", "Clean"):
        add(label+"Client", "AWS::Cognito::UserPoolClient", {
            "UserPoolId": ref("TestUsers"), "GenerateSecret": True,
            "ClientName": label.lower(), "SupportedIdentityProviders": ["COGNITO"],
            "AllowedOAuthFlowsUserPoolClient": True, "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": ["openid", "profile"],
            "CallbackURLs": [sub("https://${"+label+"Distribution.DomainName}/api/auth/oidc/callback")],
            "LogoutURLs": [sub("https://${"+label+"Distribution.DomainName}/")],
            "ExplicitAuthFlows": ["ALLOW_REFRESH_TOKEN_AUTH"],
            "PreventUserExistenceErrors": "ENABLED", "EnableTokenRevocation": True,
            "AccessTokenValidity": 15, "IdTokenValidity": 15, "RefreshTokenValidity": 1,
            "TokenValidityUnits": {"AccessToken": "minutes", "IdToken": "minutes", "RefreshToken": "days"},
        }, "Independent confidential authorization-code client for "+label.lower()+".",
            ["Exact callbacks, PKCE in Workbench, no implicit grant or public signup."])
    add("AlarmKey", "AWS::KMS::Key", {
        "EnableKeyRotation": True,
        "KeyPolicy": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Principal": {"AWS": sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:root")},
             "Action": "kms:*", "Resource": "*"},
            {"Effect": "Allow", "Principal": {"Service": "cloudwatch.amazonaws.com"},
             "Action": ["kms:Decrypt", "kms:GenerateDataKey*"], "Resource": "*",
             "Condition": {"StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")}}},
        ]},
    }, "Encrypt alarm notifications while allowing CloudWatch to publish.",
        ["Keep CloudWatch grant scoped to this account."],
        DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
    add("Alerts", "AWS::SNS::Topic", {"KmsMasterKeyId": attr("AlarmKey", "Arn")},
        "Send test alarms to an owned machine receipt queue; no human recipients.")
    add("AlertPolicy", "AWS::SNS::TopicPolicy", {
        "Topics": [ref("Alerts")], "PolicyDocument": {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "cloudwatch.amazonaws.com"},
            "Action": "sns:Publish", "Resource": ref("Alerts"),
            "Condition": {"StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")},
                          "ArnLike": {"aws:SourceArn": sub("arn:${AWS::Partition}:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:${AWS::StackName}-*")}},
        }]}}, "Only this stack's alarms can publish service notifications.")
    add("Receipts", "AWS::SQS::Queue", {
        "SqsManagedSseEnabled": True, "MessageRetentionPeriod": 1209600,
        "VisibilityTimeout": 60,
    }, "Durable evidence that alarms were delivered; contains no credentials.")
    add("ReceiptPolicy", "AWS::SQS::QueuePolicy", {
        "Queues": [ref("Receipts")], "PolicyDocument": {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "sns.amazonaws.com"},
            "Action": "sqs:SendMessage", "Resource": attr("Receipts", "Arn"),
            "Condition": {"ArnEquals": {"aws:SourceArn": ref("Alerts")},
                          "StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")}},
        }]}}, "Only this deployment's encrypted SNS topic may deliver receipts.")
    add("ReceiptSubscription", "AWS::SNS::Subscription", {
        "Protocol": "sqs", "TopicArn": ref("Alerts"), "Endpoint": attr("Receipts", "Arn"),
        "RawMessageDelivery": True,
    }, "Exercise actual notification delivery without messaging colleagues.",
        DependsOn="ReceiptPolicy")
    for label in ("Demo", "Clean"):
        for metric, threshold, comparison in (("Ready", 1, "LessThanThreshold"),
                                             ("BackupAgeSeconds", 90000, "GreaterThanThreshold")):
            add(label+metric+"Alarm", "AWS::CloudWatch::Alarm", {
                "AlarmName": sub("${AWS::StackName}-"+label.lower()+"-"+metric),
                "Namespace": "Workbench/HostedTest", "MetricName": metric,
                "Dimensions": [{"Name": "Deployment", "Value": ref("AWS::StackName")},
                               {"Name": "Instance", "Value": label.lower()}],
                "Statistic": "Minimum" if metric == "Ready" else "Maximum",
                "Period": 60, "EvaluationPeriods": 2, "DatapointsToAlarm": 2,
                "Threshold": threshold, "ComparisonOperator": comparison,
                "TreatMissingData": "breaching", "AlarmActions": [ref("Alerts")],
                "OKActions": [ref("Alerts")],
            }, "Alert on service/worker failure or missing off-host backup; missing host samples also alarm.")
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Isolated Workbench hosted acceptance test with two workspaces, password-only test SSO, private CloudFront origin, off-host backups, and alarm receipts.",
        "Metadata": {"AWSToolsMetrics": {"AWSAgentToolkit": "aws-cloudformation@3"}},
        "Parameters": {
            "VpcId": {"Type": "AWS::EC2::VPC::Id"},
            "SubnetId": {"Type": "AWS::EC2::Subnet::Id"},
            "ImageId": {"Type": "AWS::EC2::Image::Id"},
            "CloudFrontPrefixListId": {"Type": "String", "AllowedPattern": "pl-[a-f0-9]+"},
            "InstanceType": {"Type": "String", "Default": "t3a.large", "AllowedValues": ["t3a.large", "t3a.xlarge"]},
        },
        "Resources": resources,
        "Outputs": {name: {"Value": value, "Description": name} for name, value in {
            "InstanceId": ref("Server"), "StorageBucket": ref("Storage"),
            "DemoDomain": attr("DemoDistribution", "DomainName"),
            "CleanDomain": attr("CleanDistribution", "DomainName"),
            "UserPoolId": ref("TestUsers"), "DemoClientId": ref("DemoClient"),
            "CleanClientId": ref("CleanClient"), "AlertQueueUrl": ref("Receipts"),
            "Issuer": sub("https://cognito-idp.${AWS::Region}.amazonaws.com/${TestUsers}"),
        }.items()},
    }


if __name__ == "__main__":
    Path(__file__).with_name("hosted-test.json").write_text(json.dumps(template(), indent=2)+"\n")
