FROM node:20-alpine

WORKDIR /app/frontend

# Install dependencies into the image using the exact lockfile.
# In production this is the final node_modules. In development
# the named volume shadows it — the entrypoint populates the
# volume on first start (see docker-entrypoint.sh).
COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 3000

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["npm", "run", "dev"]
