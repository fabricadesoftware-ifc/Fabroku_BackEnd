# Sistema de Logs do Fabroku

## Arquitetura

O sistema de logs permite acompanhar em tempo real o progresso de operações como criação de apps, deploy, configuração, etc.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │     │   API REST      │     │   Celery Task   │
│   (React/Vue)   │────▶│   /api/logs/    │◀────│   create_app    │
│                 │     │                 │     │                 │
│  Poll a cada 2s │     │  by-task/       │     │  AppLogManager  │
│                 │     │  stream/        │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                                  ┌─────────────────┐
                                                  │   PostgreSQL    │
                                                  │   app_logs      │
                                                  └─────────────────┘
```

## Endpoints da API

### Listar todos os logs (do usuário)
```http
GET /api/logs/
```

### Logs por aplicação
```http
GET /api/logs/by-app/{app_id}/
```

Query params:
- `level`: DEBUG, INFO, WARNING, ERROR, SUCCESS, DOKKU
- `category`: SYSTEM, CREATE, DEPLOY, CONFIG, GIT, DATABASE, DOMAIN, SSL
- `task_id`: ID da task específica
- `limit`: número de logs (default: 100)
- `offset`: paginação

### Logs por task (para acompanhar uma operação específica)
```http
GET /api/logs/by-task/{task_id}/
```

### Streaming/Polling de logs
```http
GET /api/logs/stream/{task_id}/?after={last_log_id}
```

Resposta:
```json
{
    "logs": [...],
    "last_id": 123,
    "count": 5,
    "has_more": false
}
```

### Resumo de uma operação
```http
GET /api/logs/summary/{task_id}/
```

Resposta:
```json
{
    "task_id": "abc123",
    "app_id": 1,
    "app_name": "meu-app",
    "total_logs": 25,
    "current_progress": 75,
    "last_message": "Configurando Git...",
    "last_level": "INFO",
    "started_at": "2024-01-01T10:00:00Z",
    "last_update": "2024-01-01T10:05:00Z",
    "has_errors": false,
    "is_complete": false
}
```

### Limpar logs de uma aplicação
```http
DELETE /api/logs/clear/{app_id}/
```

## Exemplo de Uso no Frontend (React)

```typescript
import { useState, useEffect, useCallback } from 'react';

interface Log {
  id: number;
  message: string;
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'SUCCESS' | 'DOKKU';
  level_display: string;
  category: string;
  category_display: string;
  progress: number;
  created_at: string;
  metadata: Record<string, any>;
}

interface StreamResponse {
  logs: Log[];
  last_id: number | null;
  count: number;
  has_more: boolean;
}

function useLogStream(taskId: string | null) {
  const [logs, setLogs] = useState<Log[]>([]);
  const [progress, setProgress] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [lastId, setLastId] = useState<number | null>(null);

  const fetchLogs = useCallback(async () => {
    if (!taskId) return;

    const url = lastId
      ? `/api/logs/stream/${taskId}/?after=${lastId}`
      : `/api/logs/stream/${taskId}/`;

    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`,
      },
    });

    const data: StreamResponse = await response.json();

    if (data.logs.length > 0) {
      setLogs(prev => [...prev, ...data.logs]);
      setLastId(data.last_id);

      // Atualiza progresso baseado no último log
      const lastLog = data.logs[data.logs.length - 1];
      setProgress(lastLog.progress);

      if (lastLog.level === 'ERROR') {
        setHasError(true);
      }

      if (lastLog.progress === 100) {
        setIsComplete(true);
      }
    }
  }, [taskId, lastId]);

  useEffect(() => {
    if (!taskId || isComplete || hasError) return;

    // Poll a cada 2 segundos
    const interval = setInterval(fetchLogs, 2000);

    // Fetch inicial
    fetchLogs();

    return () => clearInterval(interval);
  }, [taskId, isComplete, hasError, fetchLogs]);

  return { logs, progress, isComplete, hasError };
}

// Componente de exemplo
function AppCreationLogs({ taskId }: { taskId: string }) {
  const { logs, progress, isComplete, hasError } = useLogStream(taskId);

  return (
    <div className="logs-container">
      {/* Progress Bar */}
      <div className="progress-bar">
        <div
          className={`progress-fill ${hasError ? 'error' : isComplete ? 'success' : ''}`}
          style={{ width: `${progress}%` }}
        />
        <span>{progress}%</span>
      </div>

      {/* Log List */}
      <div className="logs-list">
        {logs.map(log => (
          <div key={log.id} className={`log-entry log-${log.level.toLowerCase()}`}>
            <span className="log-time">
              {new Date(log.created_at).toLocaleTimeString()}
            </span>
            <span className={`log-level level-${log.level.toLowerCase()}`}>
              [{log.level_display}]
            </span>
            <span className="log-category">
              {log.category_display}
            </span>
            <span className="log-message">
              {log.message}
            </span>
          </div>
        ))}
      </div>

      {/* Status */}
      {isComplete && (
        <div className="status success">
          ✅ Aplicação criada com sucesso!
        </div>
      )}
      {hasError && (
        <div className="status error">
          ❌ Erro durante a criação. Verifique os logs acima.
        </div>
      )}
    </div>
  );
}

export { useLogStream, AppCreationLogs };
```

## CSS de exemplo

```css
.logs-container {
  font-family: 'Fira Code', monospace;
  background: #1a1a2e;
  border-radius: 8px;
  padding: 16px;
}

.progress-bar {
  height: 24px;
  background: #2d2d44;
  border-radius: 4px;
  margin-bottom: 16px;
  position: relative;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4ade80, #22c55e);
  transition: width 0.3s ease;
}

.progress-fill.error {
  background: linear-gradient(90deg, #f87171, #ef4444);
}

.progress-fill.success {
  background: linear-gradient(90deg, #4ade80, #22c55e);
}

.logs-list {
  max-height: 400px;
  overflow-y: auto;
}

.log-entry {
  padding: 4px 8px;
  font-size: 13px;
  border-left: 3px solid transparent;
}

.log-entry.log-info { border-color: #3b82f6; }
.log-entry.log-success { border-color: #22c55e; }
.log-entry.log-warning { border-color: #f59e0b; }
.log-entry.log-error { border-color: #ef4444; }
.log-entry.log-dokku { border-color: #8b5cf6; background: #1e1e3f; }

.log-time {
  color: #666;
  margin-right: 8px;
}

.log-level {
  font-weight: bold;
  margin-right: 8px;
}

.level-info { color: #3b82f6; }
.level-success { color: #22c55e; }
.level-warning { color: #f59e0b; }
.level-error { color: #ef4444; }
.level-dokku { color: #8b5cf6; }

.log-category {
  color: #888;
  margin-right: 8px;
}

.log-message {
  color: #e5e5e5;
}

.status {
  margin-top: 16px;
  padding: 12px;
  border-radius: 4px;
  text-align: center;
  font-weight: bold;
}

.status.success {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.status.error {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}
```

## Uso no Backend (Celery Tasks)

```python
from core.logs.models import AppLogManager, LogCategory

def minha_task(app_id: int, task_id: str):
    app = App.objects.get(id=app_id)
    logger = AppLogManager(app, task_id)

    # Log simples
    logger.info("Iniciando operação...", category=LogCategory.DEPLOY, progress=10)

    # Log de output do Dokku
    output = dokku_adapter.deploy(app.name_dokku)
    logger.dokku(output, command="dokku deploy", category=LogCategory.DEPLOY, progress=50)

    # Log de erro
    try:
        # operação
        pass
    except Exception as e:
        logger.error(str(e), category=LogCategory.DEPLOY, metadata={"traceback": "..."})
        raise

    # Log de sucesso
    logger.success("Deploy concluído!", category=LogCategory.DEPLOY, progress=100)
```
