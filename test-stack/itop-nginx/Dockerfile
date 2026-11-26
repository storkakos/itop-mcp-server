# TEST ONLY. iTop on nginx + PHP-FPM, the way a customer on nginx runs it.
# Build context is test-stack/ (see compose.itop-nginx.yaml): install.xml is shared with ./itop.
FROM php:8.3.37-fpm
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpng-dev libjpeg-dev libfreetype6-dev libzip-dev libxml2-dev libicu-dev libldap2-dev \
      graphviz mariadb-client unzip nginx \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j4 mysqli gd zip soap intl ldap \
    && pecl install apcu && docker-php-ext-enable apcu \
    && rm -rf /var/lib/apt/lists/*     && rm -f /etc/nginx/sites-enabled/default
RUN { echo 'memory_limit=512M'; echo 'upload_max_filesize=20M'; echo 'post_max_size=20M'; echo 'max_execution_time=300'; } \
      > /usr/local/etc/php/conf.d/itop.ini
COPY itop/install.xml /opt/itop-test/install.xml
COPY itop-nginx/entrypoint.sh /usr/local/bin/itop-nginx-entrypoint
RUN chmod +x /usr/local/bin/itop-nginx-entrypoint
ENTRYPOINT ["itop-nginx-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
