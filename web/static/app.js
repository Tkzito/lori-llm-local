document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const messageInput = document.getElementById("message-input");
  const conversation = document.getElementById("conversation");
  const historyContainer = document.getElementById("history");
  const clearHistoryBtn = document.getElementById("clear-history-btn");
  const newChatBtn = document.getElementById("new-chat-btn");
  const agentPanel = document.getElementById("agent-panel");
  const uploadFileBtn = document.getElementById("upload-file-btn");
  const fileInput = document.getElementById("file-input");
  const contextFilesList = document.getElementById("context-files-list");
  const contextEmptyState = document.getElementById("context-empty-state");
  const clearContextBtn = document.getElementById("clear-context-btn");
  const historyPanel = document.getElementById("history-panel");
  const toggleHistoryBtn = document.getElementById("toggle-history-btn");
  const toggleAgentBtn = document.getElementById("toggle-agent-btn");
  const toggleThemeBtn = document.getElementById("toggle-theme-btn");
  const agentLog = document.getElementById("agent-log");
  const sendButton = document.getElementById("send-button");
  const mainContainer = document.querySelector(".main-container");
  const agentHandleBtn = document.getElementById("agent-handle-btn");
  const contextFeedback = document.getElementById("context-feedback");
  const contextCountLabel = document.getElementById("context-count");
  const historyHandleBtn = document.getElementById("history-handle-btn");
  let socket;
  const contextFilesState = new Map(); // key => { displayName, size, path, storedName, removing }
  let contextFeedbackTimeout;

  const setHistoryPanelCollapsed = (collapsed, options = {}) => {
    if (!historyPanel) {
      if (toggleHistoryBtn) toggleHistoryBtn.disabled = false;
      return;
    }

    historyPanel.classList.toggle("collapsed", collapsed);
    if (mainContainer) {
      mainContainer.classList.toggle("history-collapsed", collapsed);
    }

    if (toggleHistoryBtn) {
      toggleHistoryBtn.classList.toggle("active", collapsed);
      toggleHistoryBtn.setAttribute("aria-pressed", collapsed ? "true" : "false");
      toggleHistoryBtn.title = collapsed ? "Mostrar histórico" : "Ocultar histórico";
      if (options.source === "toggle") {
        toggleHistoryBtn.disabled = true;
        setTimeout(() => {
          toggleHistoryBtn.disabled = false;
        }, 320);
      } else {
        toggleHistoryBtn.disabled = false;
      }
    }

    if (historyHandleBtn) {
      historyHandleBtn.setAttribute("aria-hidden", collapsed ? "false" : "true");
      historyHandleBtn.classList.toggle("is-visible", collapsed);
      if (!collapsed) {
        historyHandleBtn.disabled = false;
      }
    }

    if (!options.skipPersist) {
      try {
        localStorage.setItem("history-panel-collapsed", collapsed ? "1" : "0");
      } catch (error) {
        console.debug("Não foi possível persistir estado do histórico:", error);
      }
    }
  };

  const refreshContextEmptyState = () => {
    const hasFiles = contextFilesState.size > 0;
    if (contextEmptyState) {
      contextEmptyState.style.display = hasFiles ? "none" : "block";
    }
    if (clearContextBtn && clearContextBtn.dataset.loading !== "true") {
      clearContextBtn.disabled = !hasFiles;
    }
    if (contextCountLabel) {
      if (!contextFilesState.size) {
        contextCountLabel.textContent = "Nenhum arquivo adicionado.";
      } else if (contextFilesState.size === 1) {
        contextCountLabel.textContent = "1 arquivo adicionado.";
      } else {
        contextCountLabel.textContent = `${contextFilesState.size} arquivos adicionados.`;
      }
    }
  };

  const showContextFeedback = (message, type = "info") => {
    if (!contextFeedback) return;
    contextFeedback.textContent = message;
    contextFeedback.classList.remove("success", "error", "info", "is-visible");
    contextFeedback.classList.add(type);
    contextFeedback.classList.add("is-visible");
    clearTimeout(contextFeedbackTimeout);
    contextFeedbackTimeout = setTimeout(() => {
      contextFeedback.classList.remove("success", "error", "info", "is-visible");
      contextFeedback.textContent = "";
    }, 4000);
  };

  const removeContextFiles = async (paths) => {
    if (!paths || paths.length === 0) {
      return { ok: true, deleted: [], errors: [] };
    }
    try {
      const response = await fetch('/upload/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths }),
      });
      const payload = await response.json();
      const deletedRaw = Array.isArray(payload?.deleted) ? payload.deleted : payload?.deleted ? [payload.deleted] : [];
      const deleted = deletedRaw.map((item) => String(item));
      const rawErrors = Array.isArray(payload?.errors) ? payload.errors : payload?.errors ? [payload.errors] : [];
      const errors = rawErrors.map((item) => {
        if (!item) {
          return { path: null, error: "erro desconhecido" };
        }
        if (typeof item === "string") {
          return { path: null, error: item };
        }
        return item;
      });
      const ok = response.ok && payload?.ok !== false && errors.length === 0;
      return { ok, deleted, errors };
    } catch (error) {
      console.warn("Falha ao remover arquivos de contexto:", error);
      return { ok: false, deleted: [], errors: [{ path: null, error: error.message }] };
    }
  };

  const formatFileSize = (size) => {
    if (size === undefined || size === null) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = size;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  };

  const renderContextFiles = () => {
    contextFilesList.innerHTML = "";
    const fragment = document.createDocumentFragment();
    contextFilesState.forEach((entry, key) => {
      const data = entry || {};
      const container = document.createElement("div");
      container.className = "context-file-entry";
      container.dataset.key = key;

      const displayName = data.displayName || data.filename || data.path?.split("/").pop() || key;
      if (data.removing) {
        container.classList.add("is-removing");
      }

      const info = document.createElement("div");
      info.className = "file-info";

      const icon = document.createElement("span");
      icon.className = "file-icon";
      icon.textContent = data.icon || "📄";
      info.appendChild(icon);

      const textWrapper = document.createElement("div");
      textWrapper.className = "file-texts";

      const nameSpan = document.createElement("span");
      nameSpan.className = "file-name";
      nameSpan.title = displayName;
      nameSpan.textContent = displayName;
      textWrapper.appendChild(nameSpan);

      if (typeof data.size === "number" && data.size >= 0) {
        const sizeBadge = document.createElement("span");
        sizeBadge.className = "file-size";
        sizeBadge.textContent = formatFileSize(data.size);
        textWrapper.appendChild(sizeBadge);
      }

      info.appendChild(textWrapper);
      container.appendChild(info);

      const actions = document.createElement("div");
      actions.className = "file-actions";
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "remove-file-btn";
      removeBtn.title = "Remover arquivo do contexto";
      removeBtn.setAttribute("aria-label", `Remover ${displayName}`);
      removeBtn.disabled = Boolean(data.removing);
      removeBtn.textContent = data.removing ? "Removendo..." : "Remover";

      if (data.removing) {
        const spinner = document.createElement("span");
        spinner.className = "spinner";
        spinner.setAttribute("aria-hidden", "true");
        removeBtn.prepend(spinner);
      }

      removeBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        const current = contextFilesState.get(key);
        if (!current || current.removing) return;

        contextFilesState.set(key, { ...current, removing: true });
        renderContextFiles();

        const removalKey = current.path || current.storedName || key;
        const result = await removeContextFiles([removalKey]);
        const deletedSet = new Set((result.deleted || []).map((item) => String(item)));
        const targetKeys = [removalKey, String(removalKey), current.path, current.storedName, key].filter(Boolean);
        const wasDeleted = targetKeys.some((candidate) => deletedSet.has(candidate));

        if (wasDeleted) {
          contextFilesState.delete(key);
          renderContextFiles();
          showContextFeedback(`Arquivo "${displayName}" removido do contexto.`, "success");
        } else {
          const reverted = { ...current, removing: false };
          contextFilesState.set(key, reverted);
          renderContextFiles();
          const errorDetail = (result.errors.find((item) => item && targetKeys.includes(String(item.path))) || result.errors[0] || {});
          const message = errorDetail?.error ? `Não foi possível remover "${displayName}": ${errorDetail.error}` : `Não foi possível remover "${displayName}".`;
          showContextFeedback(message, "error");
        }
      });

      actions.appendChild(removeBtn);
      container.appendChild(actions);
      fragment.appendChild(container);
    });

    contextFilesList.appendChild(fragment);
    refreshContextEmptyState();
  };

  const setAgentPanelCollapsed = (collapsed, options = {}) => {
    if (!agentPanel) {
      if (options.source === "toggle" && toggleAgentBtn) {
        toggleAgentBtn.disabled = false;
      }
      if (options.source === "handle" && agentHandleBtn) {
        agentHandleBtn.disabled = false;
      }
      return;
    }
    agentPanel.classList.toggle("collapsed", collapsed);

    if (mainContainer) {
      mainContainer.classList.toggle("agent-collapsed", collapsed);
    }

    if (toggleAgentBtn) {
      toggleAgentBtn.classList.toggle("active", collapsed);
      toggleAgentBtn.setAttribute("aria-pressed", collapsed ? "true" : "false");
      toggleAgentBtn.title = collapsed ? "Mostrar raciocínio do agente" : "Ocultar raciocínio do agente";
    }

    if (agentHandleBtn) {
      agentHandleBtn.setAttribute("aria-hidden", collapsed ? "false" : "true");
      if (!collapsed) {
        agentHandleBtn.disabled = false;
      }
    }

    if (!options.skipPersist) {
      try {
        localStorage.setItem("agent-panel-collapsed", collapsed ? "1" : "0");
      } catch (error) {
        console.debug("Não foi possível persistir estado do painel:", error);
      }
    }

    if (options.source === "toggle" && toggleAgentBtn) {
      setTimeout(() => {
        toggleAgentBtn.disabled = false;
      }, 320);
    }
    if (options.source === "handle" && agentHandleBtn) {
      setTimeout(() => {
        agentHandleBtn.disabled = false;
      }, 320);
    }
  };

  const applyStoredTheme = () => {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const storedTheme = localStorage.getItem("lori-theme");
    const shouldUseLight = storedTheme ? storedTheme === "light" : !prefersDark;
    document.body.classList.toggle("light-theme", shouldUseLight);
  };

  applyStoredTheme();
  const storedHistoryState = localStorage.getItem("history-panel-collapsed");
  const initialHistoryCollapsed = storedHistoryState === "1"
    ? true
    : storedHistoryState === "0"
      ? false
      : historyPanel?.classList.contains("collapsed");
  setHistoryPanelCollapsed(Boolean(initialHistoryCollapsed), { skipPersist: true });

  const storedAgentState = localStorage.getItem("agent-panel-collapsed");
  const initialAgentCollapsed = storedAgentState === "1" ? true : storedAgentState === "0" ? false : agentPanel?.classList.contains("collapsed");
  setAgentPanelCollapsed(Boolean(initialAgentCollapsed), { skipPersist: true });

  // --- Carregar Histórico ---
  const loadHistory = async () => {
    try {
      const response = await fetch("/history");
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();

      if (data.error) {
        console.error("Erro ao carregar histórico:", data.error);
        historyContainer.innerHTML =
          '<div class="history-entry"><em>Erro ao carregar o histórico.</em></div>';
        return;
      }

      let groups = Array.isArray(data.groups) ? data.groups : [];
      if (!groups.length && Array.isArray(data.history) && data.history.length) {
        const fallbackGroups = new Map();
        data.history.forEach((entry) => {
          try {
            const ts = entry.started_at || entry.ts;
            const dateObj = ts ? new Date(ts) : new Date();
            const key = dateObj.toISOString().slice(0, 10);
            if (!fallbackGroups.has(key)) {
              const label = (() => {
                const today = new Date();
                const diff = Math.floor((today - new Date(key)) / (24 * 60 * 60 * 1000));
                if (diff === 0) return "Hoje";
                if (diff === 1) return "Ontem";
                if (diff > 1 && diff < 7) {
                  return dateObj.toLocaleDateString("pt-BR", { weekday: "long" });
                }
                return dateObj.toLocaleDateString("pt-BR");
              })();
              fallbackGroups.set(key, { date: key, label, conversations: [] });
            }
            fallbackGroups.get(key).conversations.push({
              ts: entry.ts,
              title: entry.title || "Nova Conversa",
              started_at: ts || dateObj.toISOString(),
              message_count: entry.message_count || entry.messages_count || 0,
              preview: entry.preview || "",
            });
          } catch (_) {
            // ignora entradas mal formadas
          }
        });
        groups = Array.from(fallbackGroups.values()).sort((a, b) => b.date.localeCompare(a.date));
        groups.forEach((group) => {
          group.conversations.sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""));
        });
      }
      if (!groups.length) {
        historyContainer.innerHTML = '<div class="history-entry"><em>Nenhum histórico encontrado.</em></div>';
        return;
      }

      historyContainer.innerHTML = "";

      groups.forEach((group) => {
        const wrapper = document.createElement("div");
        wrapper.className = "history-group";

        const header = document.createElement("div");
        header.className = "history-group-header";
        const label = document.createElement("span");
        label.className = "history-group-title";
        label.textContent = group.label || group.date || "Conversas";
        header.appendChild(label);
        const badge = document.createElement("span");
        badge.className = "history-group-count";
        badge.textContent = `${(group.conversations || []).length} conversa${(group.conversations || []).length === 1 ? "" : "s"}`;
        header.appendChild(badge);
        wrapper.appendChild(header);

        const list = document.createElement("div");
        list.className = "history-group-list";

        (group.conversations || []).forEach((entry) => {
          const historyEntry = document.createElement("div");
          historyEntry.className = "history-entry";
          historyEntry.dataset.ts = entry.ts;

          const content = document.createElement("div");
          content.className = "history-entry-content";

          const titleDiv = document.createElement("div");
          titleDiv.className = "history-title";
          titleDiv.textContent = entry.title || "Nova Conversa";
          content.appendChild(titleDiv);

          if (entry.preview) {
            const previewDiv = document.createElement("div");
            previewDiv.className = "history-preview";
            previewDiv.textContent = entry.preview;
            content.appendChild(previewDiv);
          }

          const metaDiv = document.createElement("div");
          metaDiv.className = "history-meta";
          const date = entry.started_at ? new Date(entry.started_at) : new Date(entry.ts);
          metaDiv.textContent = `${date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })} • ${entry.message_count || 0} mensagens`;
          content.appendChild(metaDiv);

          historyEntry.appendChild(content);

          const deleteIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          deleteIcon.setAttribute("class", "delete-icon");
          deleteIcon.setAttribute("viewBox", "0 0 20 20");
          deleteIcon.setAttribute("fill", "currentColor");
          deleteIcon.innerHTML = `<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />`;
          historyEntry.appendChild(deleteIcon);
          deleteIcon.addEventListener("click", (e) => {
            e.stopPropagation();
            deleteConversation(entry.ts, historyEntry);
          });

          historyEntry.addEventListener("click", () => {
            loadConversation(entry.ts);
            historyContainer.querySelectorAll('.history-entry.active').forEach(el => el.classList.remove('active'));
            historyEntry.classList.add('active');
          });

          list.appendChild(historyEntry);
        });

        wrapper.appendChild(list);
        historyContainer.appendChild(wrapper);
      });
    } catch (error) {
      console.error("Falha ao buscar histórico:", error);
      historyContainer.innerHTML =
        '<div class="history-entry"><em>Não foi possível carregar o histórico.</em></div>';
    }
  };

  // --- Carregar Conversa Específica ---
  const loadConversation = async (conversationId) => {
    try {
      const response = await fetch(`/history/${conversationId}`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();

      if (!data.ok || !data.messages) {
        console.error("Erro ao carregar conversa:", data.error);
        return;
      }

      // Limpa o painel de chat e preenche com a conversa carregada
      conversation.innerHTML = "";
      data.messages.forEach(msg => {
        const messageWrapper = document.createElement("div");
        messageWrapper.className = `message-wrapper ${msg.role}-wrapper`;

        const messageBubble = document.createElement("div");
        messageBubble.className = `message ${msg.role}-message`;
        
        if (msg.role === 'assistant') {
            const strong = document.createElement('strong');
            strong.textContent = 'Lori';
            messageBubble.appendChild(strong);
        }
        
        // Renderiza o conteúdo como Markdown
        const contentDiv = document.createElement("div");
        contentDiv.innerHTML = marked.parse(msg.content);
        messageBubble.appendChild(contentDiv);
        messageWrapper.appendChild(messageBubble);

        conversation.appendChild(messageWrapper);
      });

      // Aplica o realce de sintaxe nos blocos de código
      enhanceCodeBlocks(conversation);
      conversation.scrollTop = conversation.scrollHeight;
    } catch (error) {
      console.error("Falha ao buscar conversa:", error);
    }
  }

  // --- Excluir Conversas ---
  const deleteConversation = async (conversationId, element) => {
    if (!confirm("Tem certeza que deseja excluir esta conversa?")) return;
    try {
      const response = await fetch(`/history/${conversationId}`, { method: 'DELETE' });
      const data = await response.json();
      if (data.ok) {
        const groupNode = element.closest(".history-group");
        element.remove();
        if (groupNode && !groupNode.querySelector(".history-entry")) {
          groupNode.remove();
        }
        if (!historyContainer.querySelector(".history-entry")) {
          historyContainer.innerHTML = '<div class="history-entry"><em>Nenhum histórico encontrado.</em></div>';
        }
      } else {
        alert("Erro ao excluir a conversa.");
      }
    } catch (error) {
      console.error("Falha ao excluir conversa:", error);
      alert("Erro de conexão ao tentar excluir.");
    }
  };

  const deleteAllHistory = async () => {
    if (!confirm("ATENÇÃO: Isso apagará TODO o seu histórico de conversas. Deseja continuar?")) return;
    try {
      const response = await fetch('/history', { method: 'DELETE' });
      const data = await response.json();
      if (data.ok) {
        historyContainer.innerHTML = '<div class="history-entry"><em>Nenhum histórico encontrado.</em></div>';
      } else {
        alert("Erro ao limpar o histórico.");
      }
    } catch (error) {
      console.error("Falha ao limpar histórico:", error);
      alert("Erro de conexão ao tentar limpar o histórico.");
    }
  };

  // --- Conexão WebSocket ---
  const connectWebSocket = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

    socket.onmessage = (event) => {
      handleSocketMessage(JSON.parse(event.data));
    };

    socket.onerror = (error) => {
      console.error("WebSocket Error:", error);
      addLogEntry("error", "Erro de conexão com o servidor.");
    };
  };
  // --- Enviar Mensagem e Receber Stream ---
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = messageInput.value.trim();
    if (!message) return;

    // Adiciona a mensagem do usuário à conversa
    const userMessageWrapper = document.createElement("div");
    userMessageWrapper.className = "message-wrapper user-wrapper";
    const userMessageBubble = document.createElement("div");
    userMessageBubble.className = "message user-message";
    const userContentDiv = document.createElement("div");
    userContentDiv.textContent = message;
    userMessageBubble.appendChild(userContentDiv);
    userMessageWrapper.appendChild(userMessageBubble);
    conversation.appendChild(userMessageWrapper);

    // Limpa o input e prepara para a resposta do assistente
    messageInput.value = "";
    messageInput.style.height = 'auto'; // Reseta a altura
    sendButton.disabled = true;

    // Adiciona o indicador de "digitando"
    addTypingIndicator();
    conversation.scrollTop = conversation.scrollHeight;

    // Coleta o histórico atual da UI para enviar como contexto
    agentLog.innerHTML = ''; // Limpa o log do agente a cada novo envio
    const currentHistory = [];
    conversation.querySelectorAll('.message').forEach(div => {
        const role = div.classList.contains('user-message') ? 'user' : 'assistant';
        // Ignora o indicador de "digitando"
        if (div.classList.contains('typing-indicator')) return;

        // Pega o texto do conteúdo, ignorando o 'Lori' em negrito
        const content = div.querySelector('div')?.textContent || div.textContent;
        if (content) currentHistory.push({ role, content });
    });
    currentHistory.pop(); // Remove a div vazia do assistente que acabamos de adicionar

    // Coleta os caminhos dos arquivos de contexto
    const contextFiles = Array.from(contextFilesState.values())
      .map((item) => item.path)
      .filter(Boolean);

    // Envia a mensagem via WebSocket
    socket.send(JSON.stringify({
        message: message,
        history: currentHistory,
        agent_mode: true, // Modo agente agora é sempre ativo
        context_files: contextFiles
    }));
  });

  const addTypingIndicator = () => {
    // Remove qualquer indicador anterior para evitar duplicatas
    const existingIndicator = conversation.querySelector('.typing-indicator');
    if (existingIndicator) existingIndicator.remove();

    const indicatorWrapper = document.createElement('div');
    indicatorWrapper.className = 'message-wrapper assistant-wrapper typing-indicator';
    const indicatorBubble = document.createElement('div');
    indicatorBubble.className = 'message assistant-message';
    indicatorBubble.innerHTML = '<strong>Lori</strong><div class="dots"><span></span><span></span><span></span></div>';
    indicatorWrapper.appendChild(indicatorBubble);
    conversation.appendChild(indicatorWrapper);
    conversation.scrollTop = conversation.scrollHeight;
  };

  const addLogEntry = (type, content) => {
    const entry = document.createElement('div');
    entry.className = `agent-log-entry ${type}`;
    entry.textContent = content;
    agentLog.appendChild(entry);
    agentLog.scrollTop = agentLog.scrollHeight;
  };

  const addConfirmationPrompt = (data) => {
    const entry = document.createElement('div');
    entry.className = 'agent-log-entry confirmation-prompt';
    
    const text = document.createElement('div');
    text.textContent = `⚠️ Ação requer permissão: ${data.reason || JSON.stringify(data.args)}`;
    entry.appendChild(text);

    const buttonContainer = document.createElement('div');
    const allowBtn = document.createElement('button');
    allowBtn.textContent = 'Permitir';
    allowBtn.onclick = () => {
      socket.send(JSON.stringify({ type: 'confirmation_response', approved: true }));
      entry.remove();
    };
    const denyBtn = document.createElement('button');
    denyBtn.textContent = 'Negar';
    denyBtn.onclick = () => {
      socket.send(JSON.stringify({ type: 'confirmation_response', approved: false }));
      entry.remove();
    };
    buttonContainer.appendChild(allowBtn);
    buttonContainer.appendChild(denyBtn);
    entry.appendChild(buttonContainer);

    agentLog.appendChild(entry);
    agentLog.scrollTop = agentLog.scrollHeight;
  };

  const handleSocketMessage = (data) => {
    const typingIndicator = conversation.querySelector('.typing-indicator');
    let assistantWrapper = conversation.querySelector('.message-wrapper.assistant-wrapper:not(.typing-indicator):last-of-type');

    // Se for o primeiro chunk de conteúdo, substitui o indicador de "digitando"
    if (data.type === 'content' && typingIndicator) {
        assistantWrapper = document.createElement("div");
        assistantWrapper.className = "message-wrapper assistant-wrapper";
        // Armazena o conteúdo completo em um atributo de dados para evitar re-parse
        assistantWrapper.dataset.fullContent = "";
        const assistantBubble = document.createElement("div");
        assistantBubble.className = "message assistant-message";
        assistantBubble.innerHTML = '<strong>Lori</strong><div></div>';
        assistantWrapper.appendChild(assistantBubble);
        conversation.insertBefore(assistantWrapper, typingIndicator);
        typingIndicator.remove();
    } else if (!assistantWrapper) { // Fallback se não houver mensagem do assistente
        assistantWrapper = document.createElement("div");
        assistantWrapper.className = "message-wrapper assistant-wrapper";
        assistantWrapper.dataset.fullContent = "";
        const assistantBubble = document.createElement("div");
        assistantBubble.className = "message assistant-message";
        assistantBubble.innerHTML = '<strong>Lori</strong><div></div>';
        assistantWrapper.appendChild(assistantBubble);
        conversation.appendChild(assistantWrapper);
    }

    const contentDiv = assistantWrapper.querySelector('.message div');

    switch (data.type) {
        case 'thought':
            addLogEntry('thought', `🤔 ${data.content}`);
            break;
        case 'tool_call':
            addLogEntry('tool_call', `▶️ Usando ferramenta: ${data.data.name}(${JSON.stringify(data.data.args)})`);
            break;
        case 'tool_result':
            addLogEntry('tool_result', `◀️ Resultado: ${JSON.stringify(data.data)}`);
            break;
        case 'confirm_required':
            addConfirmationPrompt(data.data);
            break;
        case 'content':
            // Acumula o conteúdo no atributo de dados e renderiza
            assistantWrapper.dataset.fullContent += data.content;
            contentDiv.innerHTML = marked.parse(assistantWrapper.dataset.fullContent);
            enhanceCodeBlocks(assistantWrapper);
            conversation.scrollTop = conversation.scrollHeight;
            break;
        case 'error':
            addLogEntry('error', `Error: ${data.content}`);
            break;
    }
  };

  if (toggleHistoryBtn) {
    toggleHistoryBtn.addEventListener('click', (event) => {
      event.preventDefault();
      if (toggleHistoryBtn.disabled) return;
      const nextState = !(historyPanel?.classList.contains('collapsed') ?? false);
      setHistoryPanelCollapsed(nextState, { source: "toggle" });
    });
  }

  if (toggleAgentBtn) {
    toggleAgentBtn.addEventListener('click', (event) => {
      event.preventDefault();
      if (toggleAgentBtn.disabled) return;
      toggleAgentBtn.disabled = true;
      const collapsed = !agentPanel.classList.contains('collapsed');
      setAgentPanelCollapsed(collapsed, { source: "toggle" });
    });
  }

  if (agentHandleBtn) {
    agentHandleBtn.addEventListener('click', (event) => {
      event.preventDefault();
      if (agentHandleBtn.disabled) return;
      agentHandleBtn.disabled = true;
      setAgentPanelCollapsed(false, { source: "handle" });
    });
  }

  if (historyHandleBtn) {
    historyHandleBtn.addEventListener('click', (event) => {
      event.preventDefault();
      if (historyHandleBtn.disabled) return;
      historyHandleBtn.disabled = true;
      setHistoryPanelCollapsed(false, { source: "handle" });
      setTimeout(() => {
        historyHandleBtn.disabled = false;
      }, 320);
    });
  }

  if (clearContextBtn) {
    const clearContextOriginalLabel = clearContextBtn.textContent;
    clearContextBtn.addEventListener('click', async () => {
      const entries = Array.from(contextFilesState.entries());
      if (!entries.length) {
        return;
      }
      clearContextBtn.disabled = true;
      clearContextBtn.textContent = 'Limpando...';
      clearContextBtn.dataset.loading = "true";
      entries.forEach(([key, info]) => {
        const entry = info || {};
        contextFilesState.set(key, { ...entry, removing: true });
      });
      renderContextFiles();

      const removalTargets = entries.map(([key, info]) => {
        const entry = info || {};
        return entry.path || entry.storedName || key;
      });
      const result = await removeContextFiles(removalTargets);

      const deletedSet = new Set((result.deleted || []).map((item) => String(item)));
      const hadErrors = (result.errors || []).length > 0;

      let successCount = 0;
      entries.forEach(([key, info], idx) => {
        const entry = info || {};
        const target = removalTargets[idx];
        const candidateKeys = [target, String(target), entry.path, key].filter(Boolean);
        const wasDeleted = candidateKeys.some((candidate) => deletedSet.has(candidate));
        if (wasDeleted) {
          contextFilesState.delete(key);
          successCount += 1;
        } else {
          contextFilesState.set(key, { ...entry, removing: false });
        }
      });

      if (hadErrors) {
        const firstError = result.errors[0];
        const detail = firstError?.error ? ` Detalhe: ${firstError.error}.` : "";
        const prefix = successCount > 0 ? "Alguns arquivos foram removidos, mas outros falharam." : "Alguns arquivos não puderam ser removidos.";
        showContextFeedback(`${prefix}${detail}`, successCount > 0 ? "info" : "error");
      } else if (successCount > 0) {
        const message = successCount === 1 ? "Arquivo de contexto removido." : "Arquivos de contexto removidos.";
        showContextFeedback(message, "success");
      } else {
        showContextFeedback("Nenhum arquivo foi removido.", "info");
      }

      renderContextFiles();
      clearContextBtn.textContent = clearContextOriginalLabel;
      delete clearContextBtn.dataset.loading;
      clearContextBtn.disabled = contextFilesState.size === 0;
    });
  }

  if (toggleThemeBtn) {
    toggleThemeBtn.addEventListener('click', () => {
      const willBeLight = !document.body.classList.contains('light-theme');
      document.body.classList.toggle('light-theme', willBeLight);
      localStorage.setItem('lori-theme', willBeLight ? 'light' : 'dark');
    });
  }

  const startNewChat = () => {
    conversation.innerHTML = `
      <div class="message-wrapper assistant-wrapper">
        <div class="message assistant-message">
            <strong>Lori</strong>
            <div>Olá! Como posso ajudar hoje?</div>
        </div>
      </div>
    `;
    document.querySelectorAll('.history-entry.active').forEach(el => el.classList.remove('active'));
  };

  newChatBtn.addEventListener('click', startNewChat);

  // --- Lógica de Upload ---
  uploadFileBtn.addEventListener('click', () => {
    fileInput.click();
  });

  fileInput.addEventListener('change', async (event) => {
    const files = event.target.files;
    if (files.length === 0) return;

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    try {
      const response = await fetch('/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (data.ok && Array.isArray(data.files)) {
        data.files.forEach(addFileToContextList);
        if (data.files.length) {
          const count = data.files.length;
          const message = count === 1 ? `Arquivo "${data.files[0].display_name || data.files[0].filename}" adicionado ao contexto.` : `${count} arquivos adicionados ao contexto.`;
          showContextFeedback(message, "success");
        }
      } else {
        showContextFeedback(`Erro no upload: ${data.error || "Falha desconhecida."}`, "error");
      }
    } catch (error) {
      console.error("Falha no upload:", error);
      showContextFeedback("Erro de conexão durante o upload.", "error");
    }

    // Limpa o input para permitir o upload do mesmo arquivo novamente
    fileInput.value = '';
  });

 const addFileToContextList = (file) => {
    if (!file) {
      return;
    }
    const path = file.path || file.local_path || "";
    if (!path) {
      showContextFeedback("Não foi possível adicionar o arquivo ao contexto (caminho inválido).", "error");
      return;
    }
    const storedName = file.stored_name || file.storedName || "";
    const key = storedName || path || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    if (contextFilesState.has(key)) {
      return;
    }

    const label = file.display_name || file.filename || path.split("/").pop() || storedName || "arquivo";
    const extension = (label.split(".").pop() || "").toLowerCase();
    const iconMap = {
      pdf: "📕",
      csv: "📑",
      xls: "📊",
      xlsx: "📊",
      txt: "📄",
      md: "📝",
      json: "🗂️",
      doc: "📘",
      docx: "📘",
      png: "🖼️",
      jpg: "🖼️",
      jpeg: "🖼️",
      gif: "🖼️",
    };
    const icon = iconMap[extension] || "📄";
    contextFilesState.set(key, {
      displayName: label,
      filename: label,
      size: file.size,
      path,
      storedName,
      icon,
      removing: false,
    });
    renderContextFiles();
  };

  const enhanceCodeBlocks = (container) => {
    container.querySelectorAll('pre').forEach((pre) => {
      // Evita adicionar o botão múltiplas vezes
      if (pre.querySelector('.copy-code-btn')) return;

      const code = pre.querySelector('code');
      if (code) {
        hljs.highlightElement(code);
      }

      const copyButton = document.createElement('button');
      copyButton.className = 'copy-code-btn';
      copyButton.textContent = 'Copiar';
      pre.appendChild(copyButton);

      copyButton.addEventListener('click', () => {
        navigator.clipboard.writeText(code.textContent).then(() => {
          copyButton.textContent = 'Copiado!';
          setTimeout(() => { copyButton.textContent = 'Copiar'; }, 2000);
        });
      });
    });
  };

  // --- Lógica do Input ---
  messageInput.addEventListener('input', () => {
    // Habilita/desabilita o botão de envio
    sendButton.disabled = messageInput.value.trim().length === 0;

    // Auto-ajuste de altura
    messageInput.style.height = 'auto';
    messageInput.style.height = `${messageInput.scrollHeight}px`;
  });

  // Permite enviar com Enter (e nova linha com Shift+Enter)
  messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event('submit'));
    }
  });

  // Carrega o histórico ao iniciar a página
  loadHistory();
  refreshContextEmptyState();
  
  // Adiciona evento ao botão de limpar tudo
  clearHistoryBtn.addEventListener('click', deleteAllHistory);

  // Inicia a conexão WebSocket
  connectWebSocket();
});
