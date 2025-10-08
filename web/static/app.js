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
  const historyPanel = document.getElementById("history-panel");
  const toggleHistoryBtn = document.getElementById("toggle-history-btn");
  const agentLog = document.getElementById("agent-log");
  const sendButton = document.getElementById("send-button");
  let socket;

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

      if (data.history && data.history.length > 0) {
        historyContainer.innerHTML = ""; // Limpa a mensagem de "carregando"
        data.history.forEach((entry) => {
          const historyEntry = document.createElement("div");
          historyEntry.className = "history-entry";
          historyEntry.dataset.ts = entry.ts; // Armazena o ID da conversa

          const titleDiv = document.createElement("div");
          titleDiv.className = "history-title";
          titleDiv.textContent = entry.title;

          const dateDiv = document.createElement("div");
          dateDiv.className = "history-date";
          // Formata a data para ser mais amigável
          const date = new Date(entry.ts);
          dateDiv.textContent = date.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });

          historyEntry.appendChild(titleDiv);
          historyEntry.appendChild(dateDiv);
          historyContainer.appendChild(historyEntry);

          // Adiciona ícone de exclusão
          const deleteIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          deleteIcon.setAttribute("class", "delete-icon");
          deleteIcon.setAttribute("viewBox", "0 0 20 20");
          deleteIcon.setAttribute("fill", "currentColor");
          deleteIcon.innerHTML = `<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />`;
          historyEntry.appendChild(deleteIcon);
          deleteIcon.addEventListener('click', (e) => {
            e.stopPropagation(); // Impede que o clique carregue a conversa
            deleteConversation(entry.ts, historyEntry);
          });

          // Adiciona o evento de clique
          historyEntry.addEventListener("click", () => {
            loadConversation(entry.ts);
            document.querySelectorAll('.history-entry.active').forEach(el => el.classList.remove('active'));
            historyEntry.classList.add('active');
          });
        });
      } else {
        historyContainer.innerHTML =
          '<div class="history-entry"><em>Nenhum histórico encontrado.</em></div>';
      }
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
        element.remove();
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
    const contextFiles = [];
    contextFilesList.querySelectorAll('.context-file-entry').forEach(entry => {
      contextFiles.push(entry.dataset.path);
    });

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

  toggleHistoryBtn.addEventListener('click', () => {
    historyPanel.classList.toggle('collapsed');
  });

  const startNewChat = () => {
    conversation.innerHTML = `
      <div class="message assistant-message">
          <strong>Lori</strong>
          <div>Olá! Como posso ajudar hoje?</div>
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
      if (data.ok) {
        data.files.forEach(addFileToContextList);
      } else {
        alert(`Erro no upload: ${data.error}`);
      }
    } catch (error) {
      console.error("Falha no upload:", error);
      alert("Erro de conexão durante o upload.");
    }

    // Limpa o input para permitir o upload do mesmo arquivo novamente
    fileInput.value = '';
  });

  const addFileToContextList = (file) => {
    const fileEntry = document.createElement('div');
    fileEntry.className = 'context-file-entry';
    fileEntry.dataset.path = file.path;
    fileEntry.innerHTML = `
      <span>${file.filename}</span>
      <button class="remove-file-btn">✖</button>
    `;
    contextFilesList.appendChild(fileEntry);

    fileEntry.querySelector('.remove-file-btn').addEventListener('click', () => {
      fileEntry.remove();
    });
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
  
  // Adiciona evento ao botão de limpar tudo
  clearHistoryBtn.addEventListener('click', deleteAllHistory);

  // Inicia a conexão WebSocket
  connectWebSocket();
});