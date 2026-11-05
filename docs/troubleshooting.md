# Troubleshooting and Operational Diagnostics

Common issues, triage workflows, and root cause resolutions.

---

## 1. Prometheus Scraping & Target Issues

### Issue: Target reports status `DOWN` with `connection refused`
- **Symptom:** In Prometheus UI (`http://localhost:9090/targets`), node-exporter target displays red `DOWN` state.
- **Root Cause:**
  1. Node Exporter is not running on the target machine.
  2. Firewall (`ufw` or iptables) is blocking TCP port `9100`.
  3. Node Exporter bound only to `127.0.0.1` instead of `0.0.0.0`.
- **Resolution:**
  ```bash
  # Check service status on target VM
  systemctl status node_exporter.service
  
  # Check listening port
  ss -tulpn | grep 9100
  
  # Allow port in firewall
  sudo ufw allow 9100/tcp comment "Prometheus Node Exporter"
  ```

---

## 2. Alertmanager and Notification Failures

### Issue: Alerts fire in Prometheus but Telegram messages are not received
- **Symptom:** Prometheus shows alert in `FIRING` state, but no Telegram notification appears.
- **Root Cause:**
  1. Invalid or missing `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`.
  2. Outbound HTTPS traffic on port 443 blocked.
  3. Alertmanager inhibited the warning alert due to an active critical alert.
- **Resolution:**
  - Verify Alertmanager logs:
    ```bash
    docker compose logs alertmanager | grep -i telegram
    ```
  - Test bot credentials directly:
    ```bash
    curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
      -d "chat_id=<CHAT_ID>&text=Test notification"
    ```

### Issue: SMTP emails rejected
- **Symptom:** Error `535 5.7.8 Username and Password not accepted`.
- **Root Cause:** Using main Google account password instead of an **App Password**, or 2FA is required.
- **Resolution:** Generate an App Password in your email provider settings and set `SMTP_PASSWORD` in `.env`.

---

## 3. FastAPI Webhook & PostgreSQL Issues

### Issue: Backend returns HTTP 500 on webhook arrival
- **Symptom:** Alertmanager logs report `Webhook responded with status 500`.
- **Root Cause:** PostgreSQL database container is not ready, or migration schema was not applied.
- **Resolution:**
  ```bash
  # Check postgres health
  docker compose ps postgres
  
  # Inspect backend logs
  docker compose logs backend
  
  # Re-run database migrations if necessary
  docker compose exec backend alembic upgrade head
  ```

---

## 4. Automated Recovery Engine Issues

### Issue: Service failed, but recovery was skipped or failed
- **Symptom:** Incident is created in database, but `recovery_status` is `skipped` or `failed`.
- **Root Cause:**
  1. `RECOVERY_ENABLED` is set to `false` in `.env`.
  2. Target host or service is not included in `ALLOWED_RECOVERY_HOSTS` or `ALLOWED_RECOVERY_SERVICES`.
  3. Recovery cooldown is active (attempt made within `RECOVERY_COOLDOWN_SECONDS`).
  4. SSH public key authentication failed or passwordless sudo was not granted.
- **Resolution:**
  - Verify `.env` allowlists and ensure `RECOVERY_ENABLED=true`.
  - Test passwordless SSH connectivity from monitoring host:
    ```bash
    ssh -i ~/.ssh/id_rsa monitor@192.168.56.11 "sudo systemctl is-active nginx"
    ```
