# Робочий стіл Ubuntu з MySQL Server і DBeaver для предмету «Бази даних».
# Збірка: docker build -t college/mysql-desktop:latest --build-arg KASM_TAG=1.17.0 images/mysql-desktop
ARG KASM_TAG=1.17.0
FROM kasmweb/ubuntu-jammy-desktop:${KASM_TAG}
# 0 — без DBeaver (образ менший; працювати з MySQL можна з терміналу)
ARG INSTALL_DBEAVER=1

USER root
# Схема кастомізації образів Kasm: зміни профілю робимо в kasm-default-profile.
ENV HOME=/home/kasm-default-profile
ENV STARTUPDIR=/dockerstartup
WORKDIR $HOME

# У базовому образі є сторонні репозиторії (напр. HashiCorp), ключі яких іноді застарівають —
# не даємо їм зламати збірку: потрібні пакети беруться з репозиторіїв Ubuntu.
RUN (apt-get update || true) \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends mysql-server mysql-client wget \
 && if [ "$INSTALL_DBEAVER" = "1" ]; then \
      wget -q -O /tmp/dbeaver.deb https://dbeaver.io/files/dbeaver-ce_latest_amd64.deb \
      && DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/dbeaver.deb && rm -f /tmp/dbeaver.deb; \
    fi \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# MySQL працює від звичайного користувача столу (uid 1000); дані — у /var/lib/mysql-desktop контейнера.
# (Назва каталогу даних не може починатися з крапки — MySQL 8 тоді не стартує.)
# «Скинути середовище» видаляє і базу — скрипти .sql варто тримати в «Мої_файли».
RUN install -d -o 1000 -g 1000 -m 750 /var/lib/mysql-desktop
# mysql.conf.d читається після conf.d; zz- — щоб наші параметри перекрили mysqld.cnf Ubuntu.
COPY student.cnf /etc/mysql/mysql.conf.d/zz-student.cnf
COPY custom_startup.sh $STARTUPDIR/custom_startup.sh
COPY dbeaver.desktop $HOME/Desktop/dbeaver.desktop
RUN if [ "$INSTALL_DBEAVER" != "1" ]; then rm -f $HOME/Desktop/dbeaver.desktop; fi \
 && chmod 755 $STARTUPDIR/custom_startup.sh \
 && ln -sfn /home/kasm-user/Мої_файли "$HOME/Desktop/Мої_файли" \
 && chown 1000:0 $HOME && $STARTUPDIR/set_user_permission.sh $HOME

ENV HOME=/home/kasm-user
WORKDIR $HOME
RUN mkdir -p $HOME && chown -R 1000:0 $HOME
USER 1000
