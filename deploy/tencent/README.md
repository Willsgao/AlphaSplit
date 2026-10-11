# 腾讯云 OpenCloudOS 部署

本目录用于把 AlphaSplit 完整 Web 应用部署到腾讯云。应用运行在 Docker
容器中，只绑定宿主机 `127.0.0.1:8766`，由 Nginx 通过 80 端口对外提供访问。

## 首次部署

若服务器尚未安装 Docker，可先在 OpenCloudOS 上执行：

```bash
dnf install -y dnf-plugins-core git
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
```

在腾讯云服务器执行：

```bash
cd /data
git clone https://github.com/Willsgao/AlphaSplit.git
cd AlphaSplit
cp deploy/tencent/alphasplit.env.example .env
chmod 600 .env
bash deploy/tencent/install.sh
```

完成后访问：

```text
http://服务器公网IP/
```

腾讯云安全组只需放行 TCP 80。不要放行 8766，该端口只供本机 Nginx 使用。

## 运行模式

默认 `.env` 使用：

```text
ALPHASPLIT_PUBLIC_DEMO_ONLY=1
```

该模式适合公开路演，预置 Agent 响应和真实预跑演示包均可使用，同时阻止匿名
用户触发高耗时真实回测。若服务器仅供可信用户使用，可将其改为 `0`，再执行：

```bash
docker compose --env-file .env up -d
```

需要在线 Agent 时，在 `.env` 填写 `DEEPSEEK_API_KEY`。密钥不得提交到 Git。

## 更新代码

```bash
cd /data/AlphaSplit
bash deploy/tencent/update.sh
```

## 常用诊断

```bash
docker compose ps
docker compose logs -f --tail=200
curl http://127.0.0.1:8766/api/health
nginx -t
```

## HTTPS

绑定域名后，可使用 Certbot 或腾讯云证书为 Nginx 增加 HTTPS。配置 HTTPS 前，
不要把 API Key 填入网页，因为纯 HTTP 传输不能保护浏览器提交的密钥。
