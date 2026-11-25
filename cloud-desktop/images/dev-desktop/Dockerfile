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
      nodejs npm \
      default-jdk-headless \
      git curl unzip sqlite3 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Розширення VS Code для студентів (ставимо в профіль за замовчуванням).
RUN mkdir -p $HOME/.vscode/extensions \
 && (code --no-sandbox --user-data-dir /tmp/vscode-root --extensions-dir $HOME/.vscode/extensions \
      --install-extension ms-python.python \
      --install-extension ms-vscode.cpptools \
      --install-extension ms-ceintl.vscode-language-pack-uk || true) \
 && rm -rf /tmp/vscode-root

# Ярлик на робочому столі до персональної папки, яку портал монтує в ~/Мої_файли.
RUN mkdir -p $HOME/Desktop && ln -sfn /home/kasm-user/Мої_файли "$HOME/Desktop/Мої_файли"
RUN chown 1000:0 $HOME && $STARTUPDIR/set_user_permission.sh $HOME

ENV HOME=/home/kasm-user
WORKDIR $HOME
RUN mkdir -p $HOME && chown -R 1000:0 $HOME
USER 1000
