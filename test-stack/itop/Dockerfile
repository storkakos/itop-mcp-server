# TEST ONLY. Plain iTop host: Apache + mod_php, the way a customer typically runs it.
FROM php:8.3.37-apache
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpng-dev libjpeg-dev libfreetype6-dev libzip-dev libxml2-dev libicu-dev libldap2-dev \
      graphviz mariadb-client unzip \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j4 mysqli gd zip soap intl ldap \
    && pecl install apcu && docker-php-ext-enable apcu \
    && a2enmod rewrite remoteip \
    && rm -rf /var/lib/apt/lists/*
RUN { echo 'memory_limit=512M'; echo 'upload_max_filesize=20M'; echo 'post_max_size=20M'; echo 'max_execution_time=300'; } \
      > /usr/local/etc/php/conf.d/itop.ini
COPY itop.conf /etc/apache2/sites-available/000-default.conf
COPY install.xml /opt/itop-test/install.xml
COPY entrypoint.sh /usr/local/bin/itop-entrypoint
RUN chmod +x /usr/local/bin/itop-entrypoint
ENTRYPOINT ["itop-entrypoint"]
CMD ["apache2-foreground"]
