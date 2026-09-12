FROM nginx:alpine

# Frontend assets are built locally by the Git pre-commit hook.
COPY frontend/dist /usr/share/nginx/html

COPY docker/nginx.conf /etc/nginx/nginx.conf

EXPOSE 8081

CMD ["nginx", "-g", "daemon off;"]
