#!/usr/bin/env python3
"""一鍵部署 Urban Sentinel AI 到 EC2。

用法：
    python scripts/deploy_ec2.py

會自動：
1. 建立 IAM Role + Instance Profile（含 Bedrock 權限）
2. 建立 Security Group（開 80, 8000, 22）
3. 找到最新的 Amazon Linux 2023 AMI
4. 啟動 EC2，附帶 User Data 自動安裝一切
5. 等待 EC2 running，印出公開網址

前置需求：
- AWS 憑證有效（~/.aws/credentials 或環境變數）
- 憑證帳號有 EC2/IAM 的操作權限
"""

import json
import sys
import time
import base64
import boto3
from botocore.exceptions import ClientError

# ============================================================
# 設定區（改這裡就好）
# ============================================================

REGION = "us-west-2"
INSTANCE_TYPE = "t3.medium"  # 2 vCPU / 4GB，跑 FastAPI + asyncio 足夠
KEY_NAME = ""  # 留空 = 不用 SSH Key（用 EC2 Instance Connect 代替）

# 專案 Git Repo
GIT_REPO = "https://github.com/bestlatte/urban-sentinel-ai.git"
GIT_BRANCH = "victor/orch"

# 要注入到 EC2 的 .env 內容（不含 AWS 憑證——由 Instance Profile 處理）
EC2_ENV_CONTENT = """
AWS_REGION=us-west-2
BEDROCK_MODEL_ID=
BEDROCK_KNOWLEDGE_BASE_ID=
S3_DATA_BUCKET=
DECISION_LOG_TABLE=
USE_BEDROCK=true
USE_STUB_MODULES=false
LINE_CHANNEL_ACCESS_TOKEN=eRNH3H7aguhZbqWrWohXzpJDNiLgnq5uhWe9EGxRF7mJ0fMfypZu+f1/vrZUJ8ZeMDTm0BrdptiqnROjYIwnKyEoa/z2AQoJtT930vAhKZFpX9N4sv5EiCAhNfLq8FaRsX4+yHDzZg8s88sVO5zYfwdB04t89/1O/w1cDnyilFU=
LINE_TO_USER_ID=
LINE_ENABLED=true
""".strip()

# 名稱前綴（方便辨識與清理）
NAME_PREFIX = "urban-sentinel"

# ============================================================
# User Data 腳本
# ============================================================

USER_DATA_TEMPLATE = """#!/bin/bash
set -ex

# 日誌寫到 /var/log/user-data.log 方便除錯
exec > >(tee /var/log/user-data.log) 2>&1

echo "===== 開始部署 Urban Sentinel AI ====="

# 1. 安裝系統依賴
dnf update -y
dnf install -y python3.12 python3.12-pip git

# 2. Clone 專案
cd /opt
git clone --branch {branch} --single-branch {repo} urban-sentinel-ai
cd urban-sentinel-ai

# 3. 安裝 Python 依賴
python3.12 -m pip install --upgrade pip
python3.12 -m pip install -e .

# 4. 寫 .env
cat > .env << 'ENVEOF'
{env_content}
ENVEOF

# 5. 建立 systemd service
cat > /etc/systemd/system/urban-sentinel.service << 'SVCEOF'
[Unit]
Description=Urban Sentinel AI Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/urban-sentinel-ai
ExecStart=/usr/bin/python3.12 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5
Environment="PATH=/usr/local/bin:/usr/bin"

[Install]
WantedBy=multi-user.target
SVCEOF

# 6. 啟動服務
systemctl daemon-reload
systemctl enable urban-sentinel
systemctl start urban-sentinel

# 7. 用 iptables 把 80 port 轉到 8000（不需要 root 權限跑 uvicorn on 80）
iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8000

echo "===== 部署完成 ====="
echo "服務狀態："
systemctl status urban-sentinel --no-pager || true
"""


def get_user_data():
    script = USER_DATA_TEMPLATE.format(
        repo=GIT_REPO,
        branch=GIT_BRANCH,
        env_content=EC2_ENV_CONTENT,
    )
    return base64.b64encode(script.encode()).decode()


# ============================================================
# 部署邏輯
# ============================================================

def main():
    print(f"[*] 區域: {REGION}")
    print(f"[*] 實例類型: {INSTANCE_TYPE}")
    print(f"[*] Git: {GIT_REPO} @ {GIT_BRANCH}")
    print()

    ec2 = boto3.client("ec2", region_name=REGION)
    iam = boto3.client("iam", region_name=REGION)

    # --- Step 1: IAM Role ---
    role_name = f"{NAME_PREFIX}-ec2-role"
    profile_name = f"{NAME_PREFIX}-ec2-profile"

    print("[1/6] 建立 IAM Role + Instance Profile...")
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })

    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=trust_policy,
            Description="Urban Sentinel EC2 role with Bedrock access",
        )
        print(f"     建立 Role: {role_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            print(f"     Role 已存在: {role_name}")
        else:
            raise

    # 附加 Bedrock 權限
    bedrock_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                    "bedrock:ListFoundationModels",
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:ListBucket",
                ],
                "Resource": "*"
            }
        ]
    })

    policy_name = f"{NAME_PREFIX}-bedrock-policy"
    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=bedrock_policy,
        )
        print(f"     附加 inline policy: {policy_name}")
    except ClientError as e:
        print(f"     Policy 附加失敗: {e}")

    # Instance Profile
    try:
        iam.create_instance_profile(InstanceProfileName=profile_name)
        print(f"     建立 Instance Profile: {profile_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            print(f"     Instance Profile 已存在: {profile_name}")
        else:
            raise

    try:
        iam.add_role_to_instance_profile(
            InstanceProfileName=profile_name,
            RoleName=role_name,
        )
        print(f"     Role 附加到 Instance Profile")
    except ClientError as e:
        if e.response["Error"]["Code"] == "LimitExceeded":
            print(f"     Role 已附加（跳過）")
        else:
            raise

    # 等待 Instance Profile 傳播
    print("     等待 IAM 傳播（10 秒）...")
    time.sleep(10)

    # --- Step 2: Security Group ---
    print("[2/6] 建立 Security Group...")
    sg_name = f"{NAME_PREFIX}-sg"

    # 取得預設 VPC
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    if not vpcs["Vpcs"]:
        print("     ERROR: 找不到預設 VPC")
        sys.exit(1)
    vpc_id = vpcs["Vpcs"][0]["VpcId"]
    print(f"     使用預設 VPC: {vpc_id}")

    try:
        sg_resp = ec2.create_security_group(
            GroupName=sg_name,
            Description="Urban Sentinel AI - HTTP + SSH",
            VpcId=vpc_id,
        )
        sg_id = sg_resp["GroupId"]
        print(f"     建立 SG: {sg_id}")

        # 開放入站規則
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                # HTTP (port 80 → iptables 轉到 8000)
                {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                 "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTP"}]},
                # 直接存取 uvicorn (port 8000)
                {"IpProtocol": "tcp", "FromPort": 8000, "ToPort": 8000,
                 "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Uvicorn direct"}]},
                # SSH
                {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                 "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}]},
            ],
        )
        print("     入站規則已設定（80, 8000, 22）")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
            # SG 已存在，找到它
            sgs = ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [sg_name]}]
            )
            sg_id = sgs["SecurityGroups"][0]["GroupId"]
            print(f"     SG 已存在: {sg_id}")
        else:
            raise

    # --- Step 3: 找最新 Amazon Linux 2023 AMI ---
    print("[3/6] 查詢最新 Amazon Linux 2023 AMI...")
    images = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": ["al2023-ami-2023*-x86_64"]},
            {"Name": "state", "Values": ["available"]},
            {"Name": "architecture", "Values": ["x86_64"]},
        ],
    )
    sorted_images = sorted(images["Images"], key=lambda x: x["CreationDate"], reverse=True)
    if not sorted_images:
        print("     ERROR: 找不到 AL2023 AMI")
        sys.exit(1)
    ami_id = sorted_images[0]["ImageId"]
    print(f"     AMI: {ami_id} ({sorted_images[0]['Name']})")

    # --- Step 4: 檢查是否已有跑著的實例 ---
    print("[4/6] 檢查既有實例...")
    existing = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [f"{NAME_PREFIX}-server"]},
            {"Name": "instance-state-name", "Values": ["running", "pending"]},
        ]
    )
    for res in existing["Reservations"]:
        for inst in res["Instances"]:
            old_id = inst["InstanceId"]
            print(f"     終止既有實例: {old_id}")
            ec2.terminate_instances(InstanceIds=[old_id])

    # --- Step 5: 啟動 EC2 ---
    print("[5/6] 啟動 EC2 實例...")
    run_params = {
        "ImageId": ami_id,
        "InstanceType": INSTANCE_TYPE,
        "MinCount": 1,
        "MaxCount": 1,
        "SecurityGroupIds": [sg_id],
        "UserData": get_user_data(),
        "IamInstanceProfile": {"Name": profile_name},
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": f"{NAME_PREFIX}-server"},
                {"Key": "Project", "Value": "urban-sentinel-ai"},
            ],
        }],
        # 確保有公開 IP
        "NetworkInterfaces": [{
            "DeviceIndex": 0,
            "AssociatePublicIpAddress": True,
            "Groups": [sg_id],
        }],
    }
    # NetworkInterfaces 已經指定 SG，移除頂層的 SecurityGroupIds
    del run_params["SecurityGroupIds"]

    if KEY_NAME:
        run_params["KeyName"] = KEY_NAME

    resp = ec2.run_instances(**run_params)
    instance_id = resp["Instances"][0]["InstanceId"]
    print(f"     實例已建立: {instance_id}")

    # --- Step 6: 等待 running ---
    print("[6/6] 等待實例啟動...")
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])

    # 取得公開 IP
    desc = ec2.describe_instances(InstanceIds=[instance_id])
    public_ip = desc["Reservations"][0]["Instances"][0].get("PublicIpAddress")
    public_dns = desc["Reservations"][0]["Instances"][0].get("PublicDnsName")

    print()
    print("=" * 60)
    print("  部署成功！")
    print("=" * 60)
    print()
    print(f"  實例 ID:  {instance_id}")
    print(f"  公開 IP:  {public_ip}")
    print()
    print(f"  Dashboard:  http://{public_ip}/frontend/")
    print(f"  Health:     http://{public_ip}/api/health")
    print(f"  WebSocket:  ws://{public_ip}/ws")
    print()
    print("  ⚠️  User Data 腳本需要 2~3 分鐘完成安裝。")
    print("     用以下命令確認服務是否 ready：")
    print(f"     curl http://{public_ip}/api/health")
    print()
    print("  如果需要 SSH 進去除錯：")
    print(f"     aws ec2-instance-connect send-ssh-public-key \\")
    print(f"       --instance-id {instance_id} --instance-os-user ec2-user \\")
    print(f"       --ssh-public-key file://~/.ssh/id_rsa.pub")
    print(f"     ssh ec2-user@{public_ip}")
    print()
    print("  查看 User Data 日誌：")
    print("     sudo cat /var/log/user-data.log")
    print()
    print("  清理資源：")
    print(f"     aws ec2 terminate-instances --instance-ids {instance_id} --region {REGION}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
