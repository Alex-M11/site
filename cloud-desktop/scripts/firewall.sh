#!/usr/bin/env bash
# Ізоляція мережі робочих столів (тиждень 7).
#  * контейнери столів не бачать один одного (ICC вимкнено на мережі cd_desktops);
#  * не можуть звертатися до самого сервера (портал, MySQL, SSH);
#  * не можуть сканувати локальну мережу коледжу (приватні діапазони), але мають інтернет.
# Правила додаються в ланцюжок DOCKER-USER і відновлюються після перезавантаження (systemd).
#
# Дозволити навчальну підмережу (напр. стенд для лабораторних з мереж):
#   LAB_ALLOW="10.50.0.0/24" sudo -E bash scripts/firewall.sh
set -euo pipefail

NETWORK="${CD_DESKTOP_NETWORK:-cd_desktops}"
BRIDGE="cd-desktops"
SUBNET="${CD_DESKTOP_SUBNET:-172.30.0.0/16}"
LAB_ALLOW="${LAB_ALLOW:-}"

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  docker network create --driver bridge --subnet "$SUBNET" \
    -o com.docker.network.bridge.enable_icc=false \
    -o com.docker.network.bridge.name="$BRIDGE" \
    --label cloud-desktop.managed=true "$NETWORK"
fi

install -d /etc/cloud-desktop
cat > /etc/cloud-desktop/firewall-rules.sh <<EOF
#!/usr/bin/env bash
# Згенеровано scripts/firewall.sh — не редагуйте вручну.
set -e
iptables -N CD-DESKTOPS 2>/dev/null || iptables -F CD-DESKTOPS
iptables -A CD-DESKTOPS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
for net in ${LAB_ALLOW}; do iptables -A CD-DESKTOPS -d "\$net" -j RETURN; done
# DNS дозволено: DNS-сервер коледжу часто має приватну адресу.
iptables -A CD-DESKTOPS -p udp --dport 53 -j RETURN
iptables -A CD-DESKTOPS -p tcp --dport 53 -j RETURN
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
  iptables -A CD-DESKTOPS -d "\$net" -j DROP
done
iptables -A CD-DESKTOPS -p tcp --dport 25 -j DROP      # без розсилки спаму
iptables -A CD-DESKTOPS -j RETURN
iptables -C DOCKER-USER -i ${BRIDGE} -j CD-DESKTOPS 2>/dev/null || iptables -I DOCKER-USER -i ${BRIDGE} -j CD-DESKTOPS

# Доступ із контейнерів до самого сервера: лише відповіді на вже встановлені з'єднання.
iptables -C INPUT -i ${BRIDGE} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null \
  || iptables -I INPUT -i ${BRIDGE} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -C INPUT -i ${BRIDGE} -j DROP 2>/dev/null || iptables -A INPUT -i ${BRIDGE} -j DROP
EOF
chmod 755 /etc/cloud-desktop/firewall-rules.sh

cat > /etc/systemd/system/cloud-desktop-firewall.service <<'EOF'
[Unit]
Description=Cloud Desktop: ізоляція мережі робочих столів
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/etc/cloud-desktop/firewall-rules.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now cloud-desktop-firewall.service
systemctl restart cloud-desktop-firewall.service
echo "Ізоляцію мережі столів увімкнено (мережа $NETWORK, міст $BRIDGE)."
