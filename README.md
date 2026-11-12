# 🔋 Ajazz Battery Monitor (Windows System Tray)

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg)](https://microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Um utilitário ultraleve e inteligente para Windows que exibe a **porcentagem exata de bateria do seu mouse Ajazz em tempo real** diretamente na **bandeja do sistema (system tray)**, ao lado do relógio.

---

## Por que este projeto foi criado?

Os softwares oficiais da Ajazz não exibem a porcentagem numérica na bandeja do Windows nem enviam notificações nativas do sistema operacional quando a bateria está fraca ou totalmente carregada.

Este monitor resolve isso com foco absoluto em **desempenho imperceptível**, **leitura em tempo real** e **zero interferência** no driver oficial da fabricante.

---

## Funcionalidades

- **Ícone Dinâmico em Alta Resolução (DPI Aware)**:
  - Exibe o número exato da porcentagem de bateria diretamente no ícone da bandeja.
  - Cores intuitivas com borda de alto contraste (visível perfeitamente em temas Claro e Escuro):
    - 🟢 **Verde** (> 40%): Nível saudável.
    - 🟡 **Amarelo** (16% a 40%): Nível moderado.
    - 🔴 **Vermelho** (≤ 15%): Nível crítico (alerta para carregar).
    - ⚡ **Azul Elétrico / Raio**: Carregando via cabo USB.
    - ⚪ **Cinza (?)**: Mouse em modo de repouso / desconectado.
  - Mini-barra de nível de bateria integrada ao rodapé do ícone.
- **Detecção Instantânea**:
  - Detecta na hora a conexão/desconexão do cabo de carregamento USB e o retorno do modo repouso sem atrasos.
- **Zero Interferência no Driver Oficial (Arquitetura Híbrida Inteligente)**:
  - **Modo Passivo (Prioritário)**: Quando o software oficial da Ajazz (`AJAZZ Driver (X).exe`) está em execução, o monitor lê o estado do mouse diretamente da memória do processo via `ReadProcessMemory` do Windows. **Zero pacotes enviados no barramento USB/HID**, tempo de leitura de apenas **0.02 ms** e **eliminação total de popups indesejados** na tela.
  - **Modo Autônomo (Direto)**: Se o aplicativo oficial da Ajazz estiver fechado, o monitor comunica-se diretamente com o mouse usando a API nativa do Windows (`SetupAPI` / `hid.dll`) com **I/O Assíncrono (Overlapped)** e timeout ultracurto, garantindo que o app nunca trave caso o mouse entre em repouso.
- **Consumo Mínimo de Hardware**:
  - Utilização de CPU e barramento inferior a **0.05%**.
- **Notificações Nativas do Windows**:
  - Alerta ao atingir **20%** e **10%** de bateria.
  - Alerta de conclusão de recarga ao atingir **100%**.
- **Menu Completo na Bandeja (Botão Direito)**:
  - Leitura detalhada com modelo identificado, porcentagem e modo de conexão (`Cabo USB` ou `2.4G Sem Fio`).
  - 🔄 **Atualizar Agora**: força leitura e emite notificação imediata.
  - 🖱️ **Abrir Software da Ajazz**: atalho para abrir o utilitário oficial.
  - ✔️ **Iniciar com o Windows**: ativação/desativação de inicialização automática no registro do Windows com 1 clique.
  - Notificações configuráveis diretamente pelo menu.
  - ❌ **Sair**: encerramento limpo da aplicação.

---

## 🖱️ Modelos Suportados

Projetado para mouses sem fio Ajazz que utilizam o ecossistema de software Ajazz / Compx:
- **Ajazz AJ179** / **AJ179 V2** / **AJ179 V2 MAX** / **AJ179 Pro**
- **Ajazz AJ159** / **AJ159 APEX** / **AJ159 Pro** / **AJ159 MC**
- **Ajazz AJ139 Pro** / **AJ139 V2**
- **Ajazz AJ199** / **AJ199 4K**
- Outros modelos sem fio da linha Ajazz compatíveis com o protocolo HID de controle.

---

## Instalação e Requisitos

### Requisitos:
- **Windows 10** ou **Windows 11** (64-bit)
- **Python 3.8+** instalado com a opção *"Add Python to PATH"* habilitada.

### Instalação das Dependências:
Abra o PowerShell ou Terminal na pasta do projeto e execute:
```powershell
pip install -r requirements.txt
```

As únicas dependências externas são bibliotecas padrão e bem mantidas:
- `pystray` (criação e controle do ícone e menu da bandeja)
- `pillow` (renderização dinâmica de gráficos e fontes)
- `psutil` (verificação eficiente de processos em execução)

---

## 🚀 Como Executar

### Opção 1: Execução Silenciosa (Recomendada)
Dê um duplo clique no arquivo:
👉 **`Iniciar Monitor.vbs`**

Ele inicializa a aplicação em segundo plano de forma 100% invisível (sem janelas de console pretas). O ícone aparecerá instantaneamente ao lado do relógio do Windows.

### Opção 2: Linha de Comando
```powershell
pythonw ajazz_battery.pyw
```

---

## ⚙️ Iniciar com o Windows

Você não precisa criar atalhos manuais na pasta de inicialização:
1. Clique com o botão direito no ícone do monitor na bandeja do sistema.
2. Clique na opção **✔ Iniciar com o Windows**.
3. O monitor configurará a chave `Software\Microsoft\Windows\CurrentVersion\Run` no seu usuário do Windows automaticamente.

---

## 🛑 Como Encerrar o Monitor

- Clique com o botão direito no ícone da bandeja e selecione **❌ Sair**.
- Ou execute o arquivo **`Parar Monitor.bat`**.

---

## 🧠 Arquitetura Técnica

```
                       +----------------------------------+
                       |     Ajazz Battery Monitor        |
                       |       (ajazz_battery.pyw)        |
                       +-----------------+----------------+
                                         |
                                         v
                       +----------------------------------+
                       |        ajazz_mouse.py            |
                       +--------+----------------+--------+
                                |                |
                  Se driver     |                | Se driver
                 está aberto    |                | fechado
                                v                v
       +----------------------------+   +----------------------------+
       |   ReadProcessMemory (RAM)  |   | Overlapped HID (SetupAPI)  |
       |  Offset base + 0x18963C    |   | Device: MI_02 (VID: 0x248A)|
       |   Zero tráfego USB/HID     |   |   Overlapped I/O + Event   |
       |     Zero popups OSD        |   |   Timeout 40ms assíncrono  |
       +----------------------------+   +----------------------------+
```

1. **Passive Driver Memory Reading**: Inspeciona a estrutura em memória de `AJAZZ Driver (X).exe` no offset global de gerenciamento de dispositivos (`0x18963C`). Os bytes de relatório (`+0x42c`) trazem a telemetria do mouse (byte 12: carregamento, byte 13: porcentagem).
2. **Direct HID Overlapped I/O**: Caso o software não esteja em execução, utiliza chamadas diretas às APIs `CreateFileW`, `WriteFile` e `ReadFile` da `kernel32.dll` com flags `FILE_FLAG_OVERLAPPED`. Um evento assíncrono com timeout de 30-50ms impede qualquer congelamento da interface mesmo quando o mouse entra em repouso por inatividade.

---

## 📄 Licença

Este projeto está licenciado sob a licença **MIT** - consulte o arquivo [LICENSE](LICENSE) para obter mais detalhes.
