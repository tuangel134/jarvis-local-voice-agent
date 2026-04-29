#!/bin/bash
# limpiar_backups.sh - Elimina archivos .before_* del repositorio
find . -name "*.before_*" -type f -delete
find . -name "*.bak" -type f -delete
find . -name "*.backup" -type f -delete
echo "Backups antiguos eliminados"
