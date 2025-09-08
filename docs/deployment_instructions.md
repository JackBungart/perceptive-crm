# Deployment Instructions for PerceptiveControls.com

These steps outline how to host the internal CRM on your existing domain (`PerceptiveControls.com`) using a Linux server (Ubuntu) with Gunicorn and Nginx.  Adjust as needed if your environment differs (e.g., Windows IIS).

## 1. Provision a Server

1. Choose a VPS or cloud instance (AWS Lightsail, DigitalOcean, Azure VM) running Ubuntu 22.04.  Ensure it has at least 1 GB of RAM and 1 CPU.
2. Point a subdomain (e.g., `crm.perceptivecontrols.com`) to your server’s IP address via DNS.

## 2. Server Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv nginx git

# Create a system user to run the app
sudo adduser --system --group crmuser
sudo mkdir -p /opt/crm_app
sudo chown crmuser:crmuser /opt/crm_app
```

## 3. Clone the Repository

As the `crmuser` user, clone the GitHub repository:

```bash
sudo -u crmuser -H bash
cd /opt/crm_app
git clone https://github.com/JackBungart/perceptive-crm.git .
git checkout main
exit
```

## 4. Set Up Python Environment

```bash
sudo -u crmuser -H bash
cd /opt/crm_app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
exit
```

## 5. Configure Environment Variables

Create a file `/opt/crm_app/.env` and define:

```bash
SECRET_KEY=choose-a-random-secret
SMTP_SERVER=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USERNAME=youruser
SMTP_PASSWORD=yourpassword
TWILIO_ACCOUNT_SID=...   # optional
TWILIO_AUTH_TOKEN=...    # optional
TWILIO_PHONE_NUMBER=...  # optional
```

Load these variables in `run.py` or via a process manager (see below).

## 6. Gunicorn Service

Create a systemd unit file `/etc/systemd/system/crm.service`:

```ini
[Unit]
Description=Perceptive Controls CRM
After=network.target

[Service]
User=crmuser
Group=crmuser
WorkingDirectory=/opt/crm_app
EnvironmentFile=/opt/crm_app/.env
ExecStart=/opt/crm_app/venv/bin/gunicorn --bind 127.0.0.1:8000 -m 007 run:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable crm.service
sudo systemctl start crm.service
```

## 7. Nginx Reverse Proxy

Create `/etc/nginx/sites-available/crm`:

```nginx
server {
    listen 80;
    server_name crm.perceptivecontrols.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and test configuration:

```bash
sudo ln -s /etc/nginx/sites-available/crm /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 8. HTTPS (Recommended)

Use Certbot to install a free Let’s Encrypt TLS certificate:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d crm.perceptivecontrols.com
```

Renewal runs automatically.  Test the HTTPS endpoint in a browser.

## 9. Ongoing Management

* Deploy updates by pulling from GitHub: `sudo -u crmuser -H bash -c 'cd /opt/crm_app && git pull && source venv/bin/activate && pip install -r requirements.txt && systemctl restart crm.service'`.
* Monitor logs: `journalctl -u crm.service` and `/var/log/nginx/access.log`.
* Harden security: disable root login, enable UFW firewall, enforce SSH key authentication.
