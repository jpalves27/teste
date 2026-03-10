# Análise Técnica — Rede IoT IEEE 802.11ah (Wi-Fi HaLow) com Chipset Newracom NRC7394

> **Documento de referência técnica** para projeto de telemetria IoT com 200 dispositivos de borda, 3 Access Points HaLow e chipset NRC7394.  
> Última atualização: Março de 2026

---

## Sumário

1. [Visão Geral do Sistema](#1-visão-geral-do-sistema)
2. [Análise de Throughput](#2-análise-de-throughput)
3. [Análise de Latência — Diagnóstico dos 500ms em Bancada](#3-análise-de-latência--diagnóstico-dos-500ms-em-bancada)
4. [Power Save Modes do NRC7394](#4-power-save-modes-do-nrc7394)
5. [TWT (Target Wake Time) — Solução Definitiva](#5-twt-target-wake-time--solução-definitiva)
6. [Análise de Canais — 1×16MHz vs 13×2MHz](#6-análise-de-canais--116mhz-vs-132mhz)
7. [Seleção de Canal no NRC7394](#7-seleção-de-canal-no-nrc7394)
8. [Configuração Completa Recomendada](#8-configuração-completa-recomendada)
9. [Plano de Ação — Passo a Passo](#9-plano-de-ação--passo-a-passo)
10. [Referências](#10-referências)

---

## 1. Visão Geral do Sistema

### 1.1 Arquitetura

O sistema é composto por quatro camadas hierárquicas:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SERVIDOR CENTRAL                             │
│              (Polling a cada 30s: GET Report → 200B)                │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ Ethernet Gigabit
                            │
                ┌───────────▼────────────┐
                │    SWITCH DE REDE      │
                │    (100M / 1 Gbps)     │
                └──┬──────────┬──────┬───┘
                   │          │      │
         Ethernet  │ Ethernet │      │ Ethernet
                   │          │      │
         ┌─────────▼──┐  ┌────▼───┐  ┌▼──────────┐
         │  AP HaLow  │  │AP HaLow│  │ AP HaLow  │
         │    AP 1    │  │  AP 2  │  │   AP 3    │
         │ 902.5 MHz  │  │910.5MHz│  │ 918.5 MHz │
         │   2 MHz BW │  │2 MHz BW│  │  2 MHz BW │
         └─────┬───┬──┘  └───┬────┘  └──┬────────┘
               │   │         │           │
    ┌──────────▼─┐ │  ┌──────▼────┐ ┌───▼───────┐
    │ 67 STAs    │ │  │  67 STAs  │ │  66 STAs  │
    │ (IoT Edge) │ │  │(IoT Edge) │ │(IoT Edge) │
    └────────────┘ │  └───────────┘ └───────────┘
              (802.11ah / Wi-Fi HaLow)
              Sub-1GHz, Alcance: 1 km+
```

### 1.2 Parâmetros Operacionais

| Parâmetro | Valor |
|---|---|
| Total de dispositivos de borda | **200** |
| Número de Access Points | **3** |
| Distribuição por AP | **67 / 67 / 66** |
| Protocolo de transporte | **TCP** |
| Modelo de comunicação | **Polling (servidor → dispositivo)** |
| Intervalo de polling | **30 segundos** |
| Payload de resposta (report) | **200 bytes** |
| Padrão de rádio | **IEEE 802.11ah (Wi-Fi HaLow)** |
| Chipset | **Newracom NRC7394** |
| Largura de banda de canal | **2 MHz** |
| Faixa de frequência | **902–928 MHz (Sub-1GHz)** |

### 1.3 Fluxo de Dados por Ciclo

```
t=0s          t=0+281ms       t=30s
 │                │              │
 ▼                ▼              ▼
[Server GET]──►[67 Reports]  [próximo ciclo]
     │
     └─► AP 1 (67 dispositivos) ─┐
     └─► AP 2 (67 dispositivos) ─┼─► Em paralelo
     └─► AP 3 (66 dispositivos) ─┘
```

---

## 2. Análise de Throughput

### 2.1 Overhead por Camada de Protocolo

Uma transação completa (GET request + Report response) envolve os seguintes headers:

| Camada | Frame | Overhead |
|---|---|---|
| TCP Header | Request + Response | 20 bytes cada |
| IP Header | Request + Response | 20 bytes cada |
| MAC 802.11ah Header | Cada frame | ~26 bytes |
| LLC/SNAP | Cada frame | 8 bytes |
| TCP ACK | 2× por transação | ~66 bytes cada |
| PHY Preamble | Cada PPDU | ~20 bytes |

**Anatomia completa de uma transação TCP:**

```
SERVIDOR → DISPOSITIVO (GET Request)
┌─────────────────────────────────────┐
│ Payload (request): ~100B            │
│ TCP Header:          20B            │
│ IP Header:           20B            │
│ MAC 802.11ah:        26B            │
│ LLC/SNAP:             8B            │
│ Total GET:         ~174B (1.392b)   │
└─────────────────────────────────────┘

DISPOSITIVO → SERVIDOR (Report Response)
┌─────────────────────────────────────┐
│ Payload (report):   200B            │
│ TCP Header:          20B            │
│ IP Header:           20B            │
│ MAC 802.11ah:        26B            │
│ LLC/SNAP:             8B            │
│ Total Response:    ~274B (2.192b)   │
└─────────────────────────────────────┘

TCP ACKs (2×):
┌─────────────────────────────────────┐
│ 2 × ~66B = 132B (1.056b)           │
└─────────────────────────────────────┘

TOTAL POR TRANSAÇÃO: ~580 bytes = 4.640 bits
(sem handshake TCP — conexão persistente)
```

### 2.2 Cálculo de Throughput por AP

```
Dispositivos por AP:           67
Bytes por transação:          ~580 bytes
Bytes por ciclo (30s) por AP: 67 × 580 = ~38.860 bytes = ~310.880 bits

Throughput médio necessário:
  310.880 bits ÷ 30 segundos = ~10.363 bps ≈ 10,4 Kbps por AP
```

### 2.3 Capacidade do Canal 2MHz

O Wi-Fi HaLow em canal de 2MHz com MCS adequado oferece:

| MCS | Taxa PHY | Eficiência (~55%) | Throughput útil |
|---|---|---|---|
| MCS0 | 650 Kbps | 55% | ~357 Kbps |
| MCS1 | 1,3 Mbps | 55% | ~715 Kbps |
| MCS2 | 1,95 Mbps | 55% | ~1,07 Mbps |
| MCS3 | 2,6 Mbps | 55% | ~1,43 Mbps |
| MCS7 | 6,5 Mbps | 55% | ~3,57 Mbps |

> **Referência base para o cenário:** MCS1 → 715 Kbps úteis.

### 2.4 Utilização do Canal

```
Throughput necessário:  10,4 Kbps
Throughput disponível: 715 Kbps (MCS1, 2MHz)

Utilização = 10,4 / 715 × 100 = 1,5%

┌─────────────────────────────────────────────────────────────────┐
│ Capacidade útil do canal: 715 Kbps (100%)                      │
│ █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ Usado: 10,4 Kbps (1,5%)                   Livre: 98,5%         │
└─────────────────────────────────────────────────────────────────┘

Margem de folga: 68,7× acima do necessário
```

### 2.5 Janela Temporal de Polling

```
Tempo para transmitir 1 transação:
  4.640 bits ÷ 715.000 bps = ~6,5 ms

Polling sequencial de 67 dispositivos:
  67 × 6,5 ms = ~436 ms

Janela disponível: 30.000 ms
Canal livre após polling: 29.564 ms (98,5% do tempo)

t=0ms    t=436ms                                   t=30.000ms
  │          │                                          │
  ▼          ▼                                          ▼
[Polling]  [Idle]────────────────────────────────────[próximo]
  █████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
```

---

## 3. Análise de Latência — Diagnóstico dos 500ms em Bancada

### 3.1 O Problema Observado

Em testes de bancada com **1 único dispositivo** conectado ao AP, a latência de uma transação GET→Report foi medida em **aproximadamente 500ms**, o que parece excessivo para uma simples troca de mensagens numa rede local.

### 3.2 Causa Principal: Power Save Mode

**O NRC7394 vem com Power Save habilitado por padrão no SDK.**

No código-fonte do SDK da Newracom, encontra-se em `sample_ps_schedule`:

```c
// Trecho do SDK — configuração padrão de power save
// NRC_WIFI_LISTEN_INTERVAL_DEFAULT é um MULTIPLICADOR (número de beacons),
// não um valor em ms. O dispositivo acorda a cada N beacons.
#define NRC_WIFI_LISTEN_INTERVAL_DEFAULT    5  // acorda a cada 5 beacons

// O dispositivo "dorme" e só acorda para verificar frames buffered
// no AP a cada LISTEN_INTERVAL × BEACON_INTERVAL
```

**Cálculo do delay de wake-up:**

```
Beacon Interval padrão: 100ms (= 100 TUs × 1.024μs ≈ 102,4ms)
Listen Interval padrão: 5 (o dispositivo acorda a cada 5 beacons)

Delay de wake-up máximo = Listen Interval × Beacon Interval
Delay de wake-up máximo = 5 × 100ms = 500ms ✓

→ Bate exatamente com a latência medida!
```

### 3.3 Como o Power Save Provoca a Latência

```
t=0ms                                             t=500ms
  │                                                   │
  ▼                                                   ▼
[Server GET]──►[AP bufferiza]──►[Dispositivo acorda]──►[Responde]
                     │                    ▲
                     │    (até 5 beacons) │
                     └────────────────────┘
                       Dispositivo estava dormindo!

Sequência detalhada:
1. Servidor envia GET Request ao AP
2. AP verifica: o dispositivo está em Power Save mode
3. AP bufferiza o frame e aguarda
4. AP sinaliza via TIM no próximo beacon que há frame buffered
5. Dispositivo acorda (após até Listen_Interval × Beacon_Interval)
6. Dispositivo envia PS-Poll ao AP pedindo o frame bufferizado
7. AP envia o GET Request para o dispositivo
8. Dispositivo processa e envia o Report
9. Servidor recebe a resposta
```

### 3.4 Outras Causas Contribuintes

| Causa | Overhead estimado | % do total |
|---|---|---|
| **Power Save wake delay** | ~400ms | **80%** |
| TCP Handshake (conexão nova) | ~40ms | 8% |
| Overhead de canal/MCS baixo | ~30ms | 6% |
| Transmissão real dos dados | ~10ms | 2% |
| Processamento no MCU | ~20ms | 4% |
| **Total** | **~500ms** | **100%** |

**Observações sobre causas secundárias:**
- **TCP Handshake** ocorre se a conexão não é persistente (nova conexão a cada requisição)
- **Canal estreito + MCS0** em bancada: sinal muito forte pode causar distorção; dispositivos muito próximos ao AP podem selecionar MCS conservador por efeito de near-far
- **Saturação de sinal** em bancada: RSSI excessivamente alto pode causar problemas de AGC (Automatic Gain Control)

### 3.5 Checklist de Diagnóstico com Comandos AT do NRC7394

Execute estes comandos AT via interface serial/UART no dispositivo:

```bash
# 1. Verificar Beacon Interval configurado no AP
AT+WBI?
# Resposta esperada: +WBI:100 (100 TUs = ~102ms)

# 2. Verificar Listen Interval do dispositivo
AT+WLI?
# Resposta esperada: +WLI:5 (5 beacons = ~500ms delay)

# 3. Reduzir Listen Interval para mínimo (1 beacon ≈ 100ms)
AT+WLI=1

# 4. Desabilitar Deep Sleep para testes
AT+WDPS=0

# 5. Verificar RSSI e qualidade do canal
AT+WCCASCAN=2,2
# Formato: AT+WCCASCAN=<preferred_bw>,<optimal_ch>[,<dwell_time>]
# Retorna: % ocupação do canal (CCA%)

# 6. Verificar modo de power save atual
AT+WPS?
# Resposta: 0=desabilitado, 1=PS-Poll, 2=Non-TIM

# 7. Desabilitar power save completamente (para diagnóstico)
AT+WPS=0
```

**Resultado esperado após ajuste:**

```
Com AT+WLI=1 e AT+WPS=0:
Latência esperada: 5-15ms (vs 500ms anterior)

Decomposição após correção:
- Wake delay:        ~0ms (sem PS)
- Transmissão:      ~6,5ms
- Processamento:    ~5ms
- Total:           ~12ms ✓
```

---

## 4. Power Save Modes do NRC7394

### 4.1 Modos Disponíveis no SDK

Definidos em [`lmac_ps_common.h`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/nrc/lmac/lmac_ps_common.h):

```c
typedef enum {
    PS_MODE_NO      = 0,   // Sem power save — always-on
    PS_MODE_PSPOLL  = 1,   // Legacy PS com PS-Poll frames
    PS_MODE_NONTIM  = 2,   // Non-TIM deep sleep (802.11ah específico)
} ps_mode_e;

typedef enum {
    PS_SLEEP_MODE_NONE  = 0,  // Sem sleep (radio ativo)
    PS_SLEEP_MODE_MODEM = 1,  // Radio OFF, MCU ativo (modem sleep)
    PS_SLEEP_MODE_DEEP  = 2,  // Tudo OFF (deep sleep — máxima economia)
} ps_sleep_mode_e;
```

### 4.2 Comparativo de Modos

| Modo PS | Sleep Mode | Latência wake | Consumo estimado | Uso recomendado |
|---|---|---|---|---|
| `PS_MODE_NO` | `PS_SLEEP_MODE_NONE` | **2–5ms** | ~100% | Baixa latência, sem restrição energética |
| `PS_MODE_PSPOLL` | `PS_SLEEP_MODE_MODEM` | **100–500ms** | ~10–30% | Equilíbrio latência/energia |
| `PS_MODE_PSPOLL` | `PS_SLEEP_MODE_DEEP` | **500ms–2s** | ~2–5% | Baixo consumo, latência tolerável |
| `PS_MODE_NONTIM` | `PS_SLEEP_MODE_DEEP` | **1s–100s** | **<1%** | Máxima economia, sensor periódico |
| **TWT (802.11ah)** | `PS_SLEEP_MODE_DEEP` | **<1ms** (programado) | **<1%** | **Melhor solução: baixo consumo + latência determinística** |

### 4.3 Non-TIM Mode (Exclusivo 802.11ah)

O modo Non-TIM é exclusivo do Wi-Fi HaLow (IEEE 802.11ah) e permite que dispositivos durmam por períodos longos sem participar do mecanismo TIM (Traffic Indication Map) do beacon.

```
Fluxo Non-TIM:
1. STA negocia com AP um "Non-TIM schedule" (ex: acordar a cada 60s)
2. STA entra em deep sleep — radio completamente desligado
3. AP mantém frames buffered (por até o Non-TIM period)
4. STA acorda no horário negociado, processa frames, dorme novamente

Vantagem: consumo de bateria ~10-50× menor que PS-Poll
Desvantagem: latência imprevisível (depende do schedule acordado)
```

---

## 5. TWT (Target Wake Time) — Solução Definitiva

### 5.1 O que é TWT

TWT (Target Wake Time) é um mecanismo definido originalmente no IEEE 802.11ax (Wi-Fi 6) e adaptado para o 802.11ah, no qual o AP e o dispositivo (STA) **negociam um contrato explícito** de quando e por quanto tempo o dispositivo deve acordar.

**Diferença entre TIM (reativo) e TWT (proativo):**

```
TIM (Tradicional — Reativo):
┌──────┐         ┌──────┐
│ STA  │ dorme   │  AP  │
│      │◄────────│beacon│ "Ei, tem frame pra você" (TIM bit)
│      │         │      │
│      │─PS-Poll►│      │ STA acorda, pede frame
│      │◄── DATA─│      │ AP entrega
└──────┘         └──────┘
Problema: STA só sabe que tem dados DEPOIS de acordar para o beacon
Latência: até Listen_Interval × Beacon_Interval

TWT (Proativo — Agendado):
┌──────┐         ┌──────┐
│ STA  │ DORME   │  AP  │ AP sabe EXATAMENTE quando STA acorda
│      │         │      │ AP prepara frames com antecedência
│      │ ACORDA  │      │
│      │◄── DATA─│      │ AP entrega imediatamente (sem PS-Poll!)
│      │ dorme   │      │
└──────┘         └──────┘
Vantagem: zero contenção, latência determinística, máxima economia
```

### 5.2 Tipos de TWT

| Tipo | Descrição | Uso ideal |
|---|---|---|
| **Individual TWT** | Negociação 1:1 entre AP e cada STA | Schedules personalizados por dispositivo |
| **Broadcast TWT** | Schedule comum anunciado via beacon | Grupos de dispositivos com mesmo timing |
| **Trigger-Enabled TWT** | AP envia Trigger Frame para iniciar TX do STA | Zero contenção — AP controla quem transmite |

> **Para o cenário com 200 dispositivos e polling a cada 30s, a combinação ideal é: Individual TWT + Trigger-Enabled.**

### 5.3 Parâmetros TWT para o Cenário

#### Cálculo do TWT Wake Interval (campo de 2 bytes: exponent + mantissa)

O intervalo TWT é codificado como: `Wake Interval = Mantissa × 2^Exponent` (em microsegundos)

```
Intervalo desejado: 30 segundos = 30.000ms = 30.000.000 μs

Objetivo: encontrar exponent e mantissa que se aproximem de 30.000.000 μs

Exponent = 7  →  2^7 = 128 μs por unidade de mantissa

Mantissa = 30.000.000 / 128 = 234.375 (inteiro)
→ Mas mantissa é 16 bits (máx 65.535 = 2^16 − 1) — valor excede o limite!

Ajuste: usar TUs (Time Units = 1.024 μs)
30.000ms em TUs = 30.000 / 1.024 × 1000 = 29.296,9 TUs

Exponent para TUs: 2^7 = 128 TUs por unidade
Mantissa = 29.296,9 / 128 = 228,9 → arredondar para 229

Verificação:
229 × 128 = 29.312 TUs
29.312 × 1.024 μs = 30.015.488 μs ≈ 30.015ms ✓ (erro < 0,1%)
```

#### Cálculo do Minimum Wake Duration (campo de 1 byte, unidade = 256μs)

O wake duration deve cobrir toda a transação:

```
Transação completa (Trigger-Enabled TWT):
  Trigger Frame (AP→STA):     ~66B → ~0,8ms em MCS1/2MHz
  SIFS:                              16μs
  GET Request (AP→STA):      ~174B → ~2,4ms em MCS1/2MHz
  SIFS:                              16μs
  Report Response (STA→AP):  ~274B → ~3,1ms em MCS1/2MHz
  SIFS:                              16μs
  ACK (AP→STA):               ~66B → ~0,8ms em MCS1/2MHz
  ────────────────────────────────────────
  Total transmissão:               ~7,1ms
  Margem de segurança (50%):       ~3,6ms
  Guard time:                      ~1ms
  ─────────────────────────────────────────
  Wake Duration necessário:       ~12ms → arredondar para 16ms

Conversão para unidades de 256μs:
  16ms / 0,256ms = 62,5 → arredondar para 64 unidades = 16.384μs ≈ 16ms
```

#### TWT Start Time — Escalonamento de 200 STAs

Para evitar colisões, cada STA recebe um horário de início diferente:

```
Espaçamento mínimo entre STAs: 5ms (1 wake duration + guard)

Distribuição por AP (67 STAs):
  STA_1:  T_base + 0ms
  STA_2:  T_base + 5ms
  STA_3:  T_base + 10ms
  ...
  STA_67: T_base + 330ms

Janela total por AP: 67 × 5ms = 335ms
Canal livre após polling: 30.000ms - 335ms = 29.665ms (98,9%)

Distribuição global (200 STAs em 3 APs — paralelo):
  AP1 (67 STAs): T_base, ..., T_base + 330ms
  AP2 (67 STAs): T_base, ..., T_base + 330ms  (canal independente)
  AP3 (66 STAs): T_base, ..., T_base + 325ms  (canal independente)

Como os 3 APs operam em canais separados (902.5, 910.5, 918.5 MHz),
os schedules podem ser idênticos sem interferência.
```

### 5.4 Configuração TWT no NRC7394

O código TWT está em [`package/lib/hostap/wpa_supplicant/twt.c`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/hostap/wpa_supplicant/twt.c) e [`ctrl_iface.c`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/hostap/wpa_supplicant/ctrl_iface.c).

**Comando TWT_SETUP via wpa_supplicant:**

```bash
# Configuração TWT para STA (dispositivo de borda)
# Intervalo de ~30s com Trigger-Enabled e Implicit

TWT_SETUP \
  dialog=1 \
  exponent=7 \
  mantissa=229 \
  min_twt=64 \
  setup_cmd=0 \
  requestor=1 \
  trigger=1 \
  implicit=1 \
  flow_type=0 \
  flow_id=0
```

**Tabela completa dos campos do TWT Information Element:**

| Campo | Valor | Significado |
|---|---|---|
| `dialog` | `1` | Dialog token para matching request/response |
| `setup_cmd` | `0` | Request (STA solicita ao AP) |
| `requestor` | `1` | STA é o requestor |
| `trigger` | `1` | **Trigger-Enabled** (AP envia Trigger Frame) |
| `implicit` | `1` | Wake times são implicitamente calculados (base + n×interval) |
| `flow_type` | `0` | Announced (STA avisa que vai dormir) |
| `flow_id` | `0` | Identificador do flow TWT (0–7) |
| `exponent` | `7` | Exponent para cálculo do intervalo |
| `mantissa` | `229` | Mantissa → intervalo de ~30.015ms |
| `min_twt` | `64` | Minimum wake duration = 64 × 256μs = 16.384μs ≈ 16ms |

### 5.5 Fluxo de Negociação TWT

```
      STA                    AP
       │                      │
       │── TWT Setup Request ─►│  (exponent=7, mantissa=229, trigger=1)
       │                      │
       │                      │ AP calcula start time e offset para este STA
       │                      │ AP verifica disponibilidade no schedule
       │                      │
       │◄─ TWT Setup Response ─│  (Accept, start_time=T_n, same params)
       │                      │
       │  [Acordo estabelecido]│
       │                      │
       │  STA entra em sleep  │
       │  (deep sleep até T_n)│
       │                      │
```

### 5.6 Fluxo Operacional com Trigger-Enabled TWT

```
      STA                    AP                  Servidor
       │                      │                      │
       │  [dormindo]          │                      │
       │                      │                      │
t=T_n  │                      │                      │
       │◄─ Trigger Frame ─────│  AP "acorda" a STA   │
       │                      │                      │
       │                      │◄──── GET Request ────│
       │                      │                      │
       │◄─── GET Request ─────│  AP repassa à STA    │
       │                      │                      │
       │─── Report Response ─►│  STA responde com    │
       │    (200 bytes)        │    telemetria        │
       │                      │──── Report ─────────►│
       │                      │                      │
       │◄──── ACK ────────────│                      │
       │                      │                      │
       │  [volta a dormir]    │                      │
       │  (até T_n + interval)│                      │
```

**Latência com Trigger-Enabled TWT:**

```
Latência total = Trigger → ACK = ~7–12ms (determinístico, sem contenção)
Jitter: < 1ms (frame já buffered no AP antes do trigger)
```

### 5.7 Tolerância a Falhas

Com 29,7 segundos de margem por ciclo, o sistema suporta múltiplas tentativas:

| Taxa de falha | Retentativas necessárias | Tempo extra | Status |
|---|---|---|---|
| 0% | 0 | 0ms | ✅ Nominal |
| 10% (20 STAs) | 20 | ~200ms | ✅ OK |
| 25% (50 STAs) | 50 | ~500ms | ✅ OK |
| 50% (100 STAs) | 100 | ~1.000ms | ✅ OK |
| 75% (150 STAs) | 150 | ~1.500ms | ✅ OK |
| 90% (180 STAs) | 180 | ~1.800ms | ✅ OK |
| 100% (200 STAs) | 200 | ~2.000ms | ✅ OK (28s sobra) |

> **Conclusão:** Com a margem de 29,7s, mesmo uma falha catastrófica de 100% dos dispositivos (todos precisando de retentativa) ainda deixa 28 segundos livres no ciclo.

### 5.8 Duty Cycle e Vida Útil de Bateria

```
Wake Duration: 16ms (configurado)
Sleep Duration: 30.000ms - 16ms = 29.984ms

Duty Cycle = 16ms / 30.000ms = 0,053%

Consumo estimado (valores típicos NRC7394):
  Em transmissão (TX):   ~150mA @ 3.3V
  Em recepção (RX):      ~80mA @ 3.3V
  Em deep sleep:         ~10μA @ 3.3V

Consumo médio:
  I_avg = (0,016s × 150mA + 29,984s × 0,010mA) / 30s
  I_avg = (2,4 + 0,3) / 30 mA = ~0,09 mA

Estimativa de vida útil por tipo de bateria:
```

| Bateria | Capacidade | Vida estimada |
|---|---|---|
| 2× AA Alcalina | 2.500 mAh | **~2.500 / 0,09 ≈ 27.778h ≈ 3,2 anos** |
| 2× AA Litio | 3.000 mAh | **~3.000 / 0,09 ≈ 33.333h ≈ 3,8 anos** |
| Célula C Alcalina | 8.000 mAh | **~8.000 / 0,09 ≈ 88.888h ≈ 10 anos** |
| Célula D Alcalina | 15.000 mAh | **~15.000 / 0,09 ≈ 166.666h ≈ 19 anos** |

> ⚠️ Estes valores são estimativas. O consumo real inclui processamento do MCU, sensores, e eventuais retransmissões.

---

## 6. Análise de Canais — 1×16MHz vs 13×2MHz

### 6.1 Espectro Disponível (902–928 MHz)

A faixa Sub-1GHz no Brasil (Res. Anatel 680/2017) oferece 26 MHz:

```
902 MHz                                                    928 MHz
 │                                                              │
 ▼                                                              ▼
 ├──────────────────────────────────────────────────────────────┤
 │                    26 MHz disponíveis                        │
 ├──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──────────────────────┤
 │1 │2 │3 │4 │5 │6 │7 │8 │9 │10│11│12│13│  ← Canais de 2MHz   │
 ├──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘                     │
 │  Freq. centrais: 903, 905, 907, 909, 911, 913, 915,         │
 │                  917, 919, 921, 923, 925, 927 MHz            │
 ├──────────────────────────────────────────────────────────────┤

Channelization possível:
  26 × 1MHz  │ 13 × 2MHz  │ 6 × 4MHz  │ 3 × 8MHz  │ 1 × 16MHz
```

### 6.2 Comparação Detalhada: 1×16MHz vs 13×2MHz

| Métrica | 1×16MHz | 13×2MHz | Vantagem |
|---|---|---|---|
| Taxa PHY máxima por AP | ~10,4 Mbps | ~1,3 Mbps | 16MHz |
| Throughput necessário por AP | 10,4 Kbps | 10,4 Kbps | Empate |
| Throughput agregado (3 APs) | ~10,4 Mbps (1 canal) | ~3,9 Mbps (3 canais) | 16MHz |
| **Alcance estimado** | ~200–500m | **~1.000m+** | **2MHz** |
| Canais independentes disponíveis | 1 | 13 | **2MHz** |
| Resiliência a interferência | ⚠️ Frágil | ✅ Robusta | **2MHz** |
| Consumo energético do STA | Maior | **Menor** | **2MHz** |
| Sensibilidade do receptor | -89 dBm | **-96 dBm** | **2MHz** |
| Penetração em obstáculos | Menor | **Maior** | **2MHz** |

### 6.3 Cálculo para o Cenário Específico com 2MHz

```
Carga por AP:
  Throughput necessário: 10,4 Kbps
  Throughput disponível: 715 Kbps (MCS1, 2MHz)

Utilização: 10,4 / 715 = 1,5%

Conclusão: Canal de 2MHz é mais do que suficiente.
Usar 16MHz seria "overkill" desnecessário, perdendo alcance sem ganho real.
```

### 6.4 Impacto no Alcance — Fórmula de Friis + Ganho de Sensibilidade

Canais mais estreitos têm **menor ruído térmico**, o que aumenta a sensibilidade:

```
Ruído térmico = kTB
  B = bandwidth em Hz
  k = 1.38×10⁻²³ J/K
  T = 290K (temperatura ambiente)

Comparação de ruído:
  N_16MHz = -174 dBm/Hz + 10×log10(16×10⁶) = -174 + 72,0 = -102 dBm
  N_2MHz  = -174 dBm/Hz + 10×log10(2×10⁶)  = -174 + 63,0 = -111 dBm

Ganho de sensibilidade: -111 - (-102) = -9 dB
→ Dispositivo "enxerga" sinais 9 dB mais fracos com 2MHz vs 16MHz

Impacto no alcance (modelo espaço livre, path loss ∝ d²):
  Ganho de 9 dB → fator de distância = 10^(9/20) ≈ 2,8×
  
Alcance comparativo:
  16MHz: ~200m  →  2MHz: ~200m × 2,8 ≈ 560m
  (em ambiente real com obstáculos, o ganho é ainda mais significativo)
```

### 6.5 Análise de Resiliência a Interferência

```
Cenário com 1×16MHz:
┌──────────────────────────────────────────────────┐
│ Canal único (16MHz)                              │
│ ████████████████ ← interferência afeta TODO      │
│ ████████████████   o espectro                   │
│ 200 dispositivos afetados simultaneamente        │
└──────────────────────────────────────────────────┘

Cenário com 13×2MHz:
┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
│1 │2 │3 │X │5 │6 │7 │8 │9 │10│11│12│13│ ← interferência
│  │  │  │XX│  │  │  │  │  │  │  │  │  │   afeta 1 canal
│  │  │  │XX│  │  │  │  │  │  │  │  │  │   (~67 dispositivos)
└──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘
12 canais restantes intactos → 133 dispositivos operacionais
```

### 6.6 Recomendação: 3 Canais de 2MHz

Para o cenário com 3 APs, a recomendação é:

```
AP 1: Canal central 902.5 MHz, BW = 2MHz
AP 2: Canal central 910.5 MHz, BW = 2MHz  (separação: 8MHz)
AP 3: Canal central 918.5 MHz, BW = 2MHz  (separação: 8MHz)

Separação entre canais: 8 MHz >> 2 MHz (BW)
→ Zero sobreposição espectral entre APs
→ Interferência co-canal praticamente nula
```

---

## 7. Seleção de Canal no NRC7394

### 7.1 Quem Escolhe o Canal

Na arquitetura 802.11ah, **o AP sempre define o canal**. As STAs (dispositivos de borda) descobrem o canal via scan (ativo ou passivo) e se conectam ao AP no canal anunciado. O AP publica seu canal nos beacons e nos probe responses.

### 7.2 Três Formas de Escolher o Canal no AP

#### Forma 1: Canal Fixo Manual

Via código (em `wifi_config.h` ou equivalente):

```c
// Configuração estática de canal no AP
#define NRC_WIFI_CHANNEL    36       // número do canal
#define NRC_WIFI_CHANNEL_BW 2        // BW em MHz (1, 2, 4, 8, 16)

// Programaticamente:
nrc_wifi_set_channel_freq_bw(
    freq_mhz,    // Ex: 9025 para 902.5 MHz
    bw_mhz       // Ex: 2 para 2MHz
);
```

**Vantagem:** Totalmente determinístico, sem variação entre reinicializações.

#### Forma 2: Seleção Automática via CCA Scan

No arquivo de configuração do AP:

```c
// Em wifi_config_ap.h ou equivalente
#define WIFI_AP_OPTIMAL_CHANNEL_ENABLE  1  // Habilitar seleção automática

// O AP fará CCA scan ao inicializar e escolherá o canal mais limpo
```

#### Forma 3: CCA Scan via Comando AT

```bash
# Sintaxe: AT+WCCASCAN=<pref_bw>,<optimal_ch>[,<dwell_time>]
# pref_bw: largura de banda preferida (1, 2, 4, 8, 16 MHz)
# optimal_ch: número de canais ótimos a retornar
# dwell_time: tempo de escuta por canal em ms (padrão: 100ms)

# Exemplo: scan em 2MHz, retornar top-5 canais, 200ms por canal
AT+WCCASCAN=2,5,200

# Retorno esperado:
# +WCCASCAN:1,3,5,7,9  (canais em ordem crescente de ocupação)
```

### 7.3 Como o CCA Scan Funciona

```
CCA = Clear Channel Assessment

Para cada canal disponível:
┌─────────────────────────────────────────────────┐
│ 1. AP sintoniza no canal                        │
│ 2. Escuta pelo dwell_time (padrão: 100ms)       │
│ 3. Mede % do tempo com energia > threshold      │
│    (CCA Threshold: geralmente -62 dBm)          │
│ 4. CCA% = (tempo ocupado / dwell_time) × 100    │
└─────────────────────────────────────────────────┘

Resultado: ranking dos canais por CCA% (menor = mais limpo)
Função: nrc_wifi_softap_get_best_ch()

Exemplo de resultado:
  Canal 902.5 MHz: CCA% = 2%   ← mais limpo (1º escolha)
  Canal 910.5 MHz: CCA% = 5%   ← 2ª escolha
  Canal 918.5 MHz: CCA% = 8%   ← 3ª escolha
  Canal 906.5 MHz: CCA% = 45%  ← evitar (interferência)
  Canal 914.5 MHz: CCA% = 67%  ← evitar (saturado)
```

### 7.4 Plano de Canais Recomendado para 3 APs

```
┌────────────────────────────────────────────────────────────────┐
│ AP 1  │ freq=9025 (902.5 MHz) │ bw=2MHz │ 67 STAs             │
│ AP 2  │ freq=9105 (910.5 MHz) │ bw=2MHz │ 67 STAs             │
│ AP 3  │ freq=9185 (918.5 MHz) │ bw=2MHz │ 66 STAs             │
├────────────────────────────────────────────────────────────────┤
│ Separação entre APs: 8 MHz                                     │
│ (máxima separação para canais de 2MHz em 26MHz de espectro)    │
└────────────────────────────────────────────────────────────────┘

Configuração de cada AP (código C):
```

```c
// AP 1
nrc_wifi_set_channel_freq_bw(9025, 2);  // 902.5 MHz, 2MHz BW

// AP 2
nrc_wifi_set_channel_freq_bw(9105, 2);  // 910.5 MHz, 2MHz BW

// AP 3
nrc_wifi_set_channel_freq_bw(9185, 2);  // 918.5 MHz, 2MHz BW
```

### 7.5 Estratégia: CCA Scan na Instalação + Canal Fixo em Produção

```
FASE 1 — INSTALAÇÃO:
┌─────────────────────────────────────────────────────┐
│ 1. Executar AT+WCCASCAN=2,5,500 em cada AP          │
│ 2. Identificar os 3 canais mais limpos              │
│ 3. Anotar os canais (ex: 9025, 9105, 9185)          │
│ 4. Verificar separação mínima de 4MHz entre canais  │
└─────────────────────────────────────────────────────┘

FASE 2 — PRODUÇÃO:
┌─────────────────────────────────────────────────────┐
│ Canal fixo hardcoded nos APs                        │
│ Motivo: determinístico, sem variação entre resets   │
│ Código: nrc_wifi_set_channel_freq_bw(freq, 2)       │
└─────────────────────────────────────────────────────┘

FASE 3 — MONITORAMENTO CONTÍNUO:
┌─────────────────────────────────────────────────────┐
│ CCA scan periódico (ex: 1×/semana ou ao detectar    │
│ degradação de performance)                          │
│ Se CCA% > 30% → avaliar troca de canal             │
└─────────────────────────────────────────────────────┘
```

### 7.6 Otimização do STA Scan

Por padrão, os dispositivos HaLow fazem scan em todos os canais suportados, o que pode ser lento. Para acelerar conexão e reconexão:

```c
// Em wifi_config_sta.h ou equivalente — restringir scan aos canais dos APs
static const int SCAN_CHANNEL_LIST[] = {
    9025,  // AP 1: 902.5 MHz
    9105,  // AP 2: 910.5 MHz
    9185,  // AP 3: 918.5 MHz
};
#define SCAN_CHANNEL_LIST_SIZE  3

// Resultado: scan de 3 canais × 100ms ≈ 300ms (vs. scan completo de 2-5s)
```

---

## 8. Configuração Completa Recomendada

### 8.1 Tabela de Parâmetros Consolidados

| Parâmetro | Valor Recomendado | Justificativa |
|---|---|---|
| **Canal BW** | **2 MHz** | Melhor equilíbrio alcance (+9dB) / throughput (suficiente) |
| **Canais AP 1/2/3** | **9025 / 9105 / 9185** | Máxima separação (8MHz), zero sobreposição |
| **Power Save Mode** | **TWT** | Latência determinística + máxima economia de energia |
| **TWT Exponent** | **7** | Intervalo de ~30s (2^7 = 128 unidades base) |
| **TWT Mantissa** | **229** | 229 × 128 TUs = ~30.015ms ≈ 30s |
| **TWT Min Wake Duration** | **64** | 64 × 256μs = 16,384ms (margem para transação completa) |
| **TWT Trigger** | **Enabled** | AP controla TX — zero contenção |
| **TWT Flow Type** | **Implicit** | AP calcula próximos wake times automaticamente |
| **Beacon Interval** | **100 TUs** | Padrão 802.11ah (~102ms) |
| **Listen Interval** | **1** | Mínimo (apenas como fallback sem TWT) |
| **Conexão TCP** | **Persistente** | Evita 3-way handshake a cada ciclo (~40ms economia) |
| **STAs por AP** | **67 / 67 / 66** | Distribuição balanceada |
| **TWT Escalonamento** | **5ms entre STAs** | Zero contenção no canal |
| **Protocolo de aplicação** | **TCP keep-alive** | Confiabilidade + eficiência |
| **Timeout por dispositivo** | **2-3 segundos** | Não travar ciclo por dispositivo não-responsivo |

### 8.2 Configuração de AP (Pseudocódigo)

```c
// === Configuração de Canal ===
nrc_wifi_set_channel_freq_bw(AP_FREQ_MHZ, 2);  // ex: 9025 para AP1

// === Configuração de Beacon ===
nrc_wifi_set_beacon_interval(100);  // 100 TUs ≈ 102ms

// === TWT (AP side) ===
twt_config_t twt_cfg = {
    .mode        = TWT_MODE_INDIVIDUAL,
    .trigger     = TWT_TRIGGER_ENABLED,
    .implicit    = true,
    .flow_type   = TWT_FLOW_ANNOUNCED,
    .start_offset_ms = 0,
    .spacing_ms  = 5,  // 5ms entre cada STA
};
nrc_wifi_ap_twt_configure(&twt_cfg);
```

### 8.3 Configuração de STA (Pseudocódigo)

```c
// === Power Save ===
nrc_wifi_set_ps_mode(PS_MODE_NO);  // Sem PS legado (usar TWT)

// === TWT (STA side — via wpa_supplicant) ===
// Executar após conexão estabelecida:
// TWT_SETUP dialog=1 exponent=7 mantissa=229 min_twt=64
//           setup_cmd=0 requestor=1 trigger=1 implicit=1
//           flow_type=0 flow_id=0

// === Scan Otimizado ===
wifi_scan_config_t scan_cfg = {
    .channel_list = {9025, 9105, 9185},
    .channel_count = 3,
};
nrc_wifi_set_scan_config(&scan_cfg);
```

---

## 9. Plano de Ação — Passo a Passo

### Fase 1: Validação em Bancada

- [ ] **Passo 1 — Diagnóstico de Power Save**
  - Conectar 1 STA ao AP em bancada
  - Medir latência baseline (deve estar ~500ms com PS padrão)
  - Executar `AT+WPS?` e `AT+WLI?` para confirmar configuração atual
  - Confirmar Listen Interval = 5 e PS habilitado

- [ ] **Passo 2 — Desabilitar Power Save e Confirmar Latência**
  - Executar `AT+WPS=0` e `AT+WLI=1`
  - Medir nova latência (deve cair para 10–20ms)
  - Se latência ainda alta: verificar MCS com `AT+WMCS?`
  - Documentar baseline sem PS

- [ ] **Passo 3 — Configurar e Validar TWT**
  - Configurar AP com TWT habilitado
  - Executar TWT_SETUP na STA com parâmetros da seção 5.4
  - Verificar que negociação TWT foi bem-sucedida
  - Medir latência com TWT (deve ser 7–15ms, determinístico)
  - Medir consumo de corrente em deep sleep (deve ser <100μA)

### Fase 2: Seleção e Configuração de Canais

- [ ] **Passo 4 — CCA Scan para Seleção de Canais**
  - Em cada local de instalação dos APs, executar:
    ```bash
    AT+WCCASCAN=2,5,500
    ```
  - Selecionar 3 canais com menor CCA%, separados por ≥4MHz
  - Documentar canais selecionados e CCA% medido

- [ ] **Passo 5 — Configurar Canais Fixos nos APs**
  - AP1: `nrc_wifi_set_channel_freq_bw(9025, 2)` (ou canal selecionado no passo 4)
  - AP2: `nrc_wifi_set_channel_freq_bw(9105, 2)`
  - AP3: `nrc_wifi_set_channel_freq_bw(9185, 2)`
  - Verificar que cada AP está operando no canal correto com `AT+WFREQ?`

- [ ] **Passo 6 — Otimizar Scan List das STAs**
  - Configurar `SCAN_CHANNEL_LIST` com apenas os 3 canais dos APs
  - Medir tempo de conexão inicial (deve ser <500ms com lista restrita)
  - Medir tempo de reconexão após perda de sinal

### Fase 3: Escala e Validação de Carga

- [ ] **Passo 7 — Escalar para 200 Dispositivos**
  - Adicionar STAs gradualmente: 10 → 50 → 100 → 200
  - Monitorar latência de polling a cada nível (deve permanecer <30ms/STA)
  - Verificar que TWT schedule está distribuído corretamente (sem colisões)
  - Medir CCA% com carga total (deve ser <5% com 67 STAs/canal)

- [ ] **Passo 8 — Testes de Carga e Tolerância a Falha**
  - Simular 10% de falhas (20 STAs não respondem)
  - Verificar que o servidor trata timeout corretamente (<2s por STA)
  - Simular queda e reconexão de um AP inteiro
  - Medir tempo de reconexão das 67 STAs ao AP substituto
  - Testar interferência intencional em 1 canal (os outros 2 devem continuar)

### Fase 4: Monitoramento em Produção

- [ ] **Passo 9 — Implementar Monitoramento**
  - Logging de latência por STA por ciclo
  - Alertas se latência > 5× baseline (indica problema de PS ou canal)
  - CCA scan semanal automatizado para detectar degradação de canal
  - Dashboard com métricas: latência p50/p95/p99, taxa de falha, CCA%

---

## 10. Referências

### Padrões e Especificações

- **IEEE 802.11ah-2016** — IEEE Standard for Information technology — Telecommunications and information exchange between systems — Local and metropolitan area networks — Specific requirements — Part 11: Wireless LAN Medium Access Control (MAC) and Physical Layer (PHY) Specifications — Amendment 2: Sub 1 GHz License Exempt Operation
- **IEEE 802.11ax-2021** — Para referência sobre TWT (implementado originalmente neste padrão)

### Hardware e SDK

- **Newracom NRC7394 SDK**: [https://github.com/newracom/nrc7394_sdk](https://github.com/newracom/nrc7394_sdk)
- **AT Command Reference**: UG-7394-006-AT_Command.pdf (disponível no portal Newracom)
- **NRC7394 Datasheet**: disponível em [https://newracom.com](https://newracom.com)

### Arquivos Relevantes no SDK

| Arquivo | Conteúdo relevante |
|---|---|
| [`lmac_ps_common.h`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/nrc/lmac/lmac_ps_common.h) | Definições de PS_MODE e PS_SLEEP_MODE |
| [`lmac_twt_common.h`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/nrc/lmac/lmac_twt_common.h) | Definições de estruturas TWT |
| [`twt.c`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/hostap/wpa_supplicant/twt.c) | Implementação TWT no wpa_supplicant |
| [`ctrl_iface.c`](https://github.com/newracom/nrc7394_sdk/blob/master/package/lib/hostap/wpa_supplicant/ctrl_iface.c) | Interface de controle (comando TWT_SETUP) |
| [`atcmd_wifi.c`](https://github.com/newracom/nrc7394_sdk/blob/master/package/src/atcmd/atcmd_wifi.c) | Implementação dos comandos AT Wi-Fi |
| [`wifi_config.h`](https://github.com/newracom/nrc7394_sdk/blob/master/package/sdk/apps/wifi_common/wifi_config.h) | Configurações de canal e PS padrão |
| `sample_ps_schedule/` | Exemplo de uso de Power Save + scheduling |

### Regulamentação (Brasil)

- **Resolução Anatel 680/2017** — Regulamento sobre Equipamentos de Radiocomunicação de Radiação Restrita
- **Sub-faixa 902–928 MHz**: Uso livre (Industrial, Científico e Médico — ISM), sem licença, potência máxima 4W EIRP

---

*Documento gerado como referência técnica interna. Valores numéricos são estimativas baseadas em especificações públicas do chipset NRC7394 e padrão IEEE 802.11ah. Resultados reais podem variar conforme ambiente de instalação, firmware utilizado e configuração específica.*
