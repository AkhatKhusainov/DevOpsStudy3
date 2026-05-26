FROM hashicorp/vault:1.19

COPY docker/vault/start-dev-vault.sh /usr/local/bin/start-dev-vault.sh

RUN sed -i 's/\r$//' /usr/local/bin/start-dev-vault.sh \
	&& chmod +x /usr/local/bin/start-dev-vault.sh

EXPOSE 8200

ENTRYPOINT ["/usr/local/bin/start-dev-vault.sh"]