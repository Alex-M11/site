# Середовище для програмування: VS Code + Python, C/C++, Node.js, Java, Git.
# Збірка: docker build -t college/dev-desktop:latest --build-arg KASM_TAG=1.17.0 images/dev-desktop
ARG KASM_TAG=1.17.0
FROM kasmweb/vs-code:${KASM_TAG}

USER root
ENV HOME=/home/kasm-default-profile
ENV STARTUPDIR=/dockerstartup
WORKDIR $HOME

# Сторонні репозиторії базового образу можуть мати застарілі ключі — не ламаємо через них збірку.
RUN (apt-get update || true) \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv python3-tk \
      build-essential gdb cmake \
      default-jdk-headless \
      git curl gnupg unzip sqlite3 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Node.js LTS з офіційного репозиторію NodeSource (у репозиторіях Ubuntu 22.04 — застаріла v12).
# Якщо репозиторій недоступний, ставимо системний Node.js, щоб збірка не зупинялася.
ARG NODE_MAJOR=22
RUN set -e; mkdir -p /etc/apt/keyrings; \
    if curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
         | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg; then \
      echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list; \
    else \
      echo "УВАГА: NodeSource недоступний — буде встановлено Node.js з репозиторію Ubuntu (стара версія)"; \
      rm -f /etc/apt/keyrings/nodesource.gpg; \
    fi; \
    (apt-get update || true); \
    if [ -f /etc/apt/sources.list.d/nodesource.list ]; then \
      DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs; \
    else \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs npm; \
    fi; \
    apt-get clean; rm -rf /var/lib/apt/lists/*; node --version

# Розширення VS Code для студентів (ставимо в профіль за замовчуванням). Потрібен доступ до
# marketplace.visualstudio.com; без нього образ збереться, але без розширень — це видно в лозі збірки.
RUN mkdir -p $HOME/.vscode/extensions \
 && if ! code --no-sandbox --user-data-dir /tmp/vscode-root --extensions-dir $HOME/.vscode/extensions \
        --install-extension ms-python.python \
        --install-extension ms-vscode.cpptools \
        --install-extension ms-ceintl.vscode-language-pack-uk; then \
      echo "УВАГА: розширення VS Code не встановлено (немає доступу до marketplace?)"; \
    fi \
 && rm -rf /tmp/vscode-root

# Ярлик на робочому столі до персональної папки, яку портал монтує в ~/Мої_файли.
RUN mkdir -p $HOME/Desktop && ln -sfn /home/kasm-user/Мої_файли "$HOME/Desktop/Мої_файли"
RUN chown 1000:0 $HOME && $STARTUPDIR/set_user_permission.sh $HOME

ENV HOME=/home/kasm-user
WORKDIR $HOME
RUN mkdir -p $HOME && chown -R 1000:0 $HOME
USER 1000
