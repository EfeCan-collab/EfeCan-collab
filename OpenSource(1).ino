#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <driver/i2s.h>
// ============================================================
// WIFI
// ============================================================

const char* WIFI_SSID =
    "";

const char* WIFI_PASSWORD =
    "";

// ============================================================
// LAPTOP SERVER
// ============================================================

// Put your LAPTOP IPv4 address here.
// Example:
// 172.20.10.3

const char* SERVER_HOST =
    "";

const uint16_t SERVER_PORT = 5000;

// ============================================================
// OLED
// ============================================================

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDR 0x3C

Adafruit_SSD1306 display(
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    &Wire,
    -1
);

// ============================================================
// BUTTONS
// ============================================================

#define BUTTON_NEXT 4
#define BUTTON_PREV 5

#define LONG_PRESS_MS 600

// ============================================================
// I2S
// ============================================================

#define I2S_PORT I2S_NUM_0

#define I2S_BCLK 2
#define I2S_WS   1

#define MIC_DIN 8
#define SPEAKER_DOUT 3

// ============================================================
// AUDIO
// ============================================================

#define MIC_SAMPLE_RATE 16000
#define TTS_SAMPLE_RATE 24000

#define MAX_RECORD_SECONDS 3

#define MAX_SAMPLES \
    (MIC_SAMPLE_RATE * MAX_RECORD_SECONDS)

// Static buffer.
// ~96 KB.
static int16_t audioBuffer[MAX_SAMPLES];

size_t recordedSamples = 0;

// ============================================================
// OLED PAGES
// ============================================================

const char* pages[] = {
    "WIFI",
    "WEATHER",
    "ROOM",
    "SPOTIFY"
};

const int PAGE_COUNT = 4;

int currentPage = 0;

// ============================================================
// WEATHER STATE
// ============================================================

const char* WEATHER_CITY = "";

float weatherTemperature = NAN;
int weatherHumidity = -1;

String weatherCondition = "";
String weatherCity = "";

unsigned long lastWeatherUpdate = 0;

const unsigned long WEATHER_UPDATE_INTERVAL = 300000UL;

// ============================================================
// WEATHER UPDATE
// ============================================================

bool updateWeather()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("[WEATHER] WiFi not connected");
        return false;
    }

    Serial.println("[WEATHER] Updating...");

    HTTPClient http;

    String url =
        String("http://") +
        SERVER_HOST +
        ":" +
        String(SERVER_PORT) +
        "/weather?city=" +
        WEATHER_CITY;

    http.setTimeout(10000);

    if (!http.begin(url))
    {
        Serial.println("[WEATHER] HTTP begin failed");
        return false;
    }

    int httpCode = http.GET();

    if (httpCode != HTTP_CODE_OK)
    {
        Serial.print("[WEATHER] HTTP error: ");
        Serial.println(httpCode);
        http.end();
        return false;
    }

    String payload = http.getString();
    http.end();

    // Parse only the fields used by the OLED.
    StaticJsonDocument<768> doc;
    StaticJsonDocument<256> filter;

    filter["status"] = true;
    filter["weather"]["city"] = true;
    filter["weather"]["condition"] = true;
    filter["weather"]["temperature_c"] = true;
    filter["weather"]["humidity_percent"] = true;

    DeserializationError error =
        deserializeJson(
            doc,
            payload,
            DeserializationOption::Filter(filter)
        );

    if (error)
    {
        Serial.print("[WEATHER] JSON error: ");
        Serial.println(error.c_str());
        return false;
    }

    if (doc["status"] != "ok")
    {
        Serial.println("[WEATHER] Server returned an error");
        return false;
    }

    JsonObject weather = doc["weather"];

    if (weather.isNull())
    {
        Serial.println("[WEATHER] Missing weather object");
        return false;
    }

    const char* city =
        weather["city"] | WEATHER_CITY;

    const char* condition =
        weather["condition"] | "unknown";

    float temperature =
        weather["temperature_c"] | NAN;

    int humidity =
        weather["humidity_percent"] | -1;

    if (isnan(temperature))
    {
        Serial.println("[WEATHER] Invalid temperature");
        return false;
    }

    weatherCity = city;
    weatherCondition = condition;
    weatherTemperature = temperature;
    weatherHumidity = humidity;
    lastWeatherUpdate = millis();

    Serial.print("[WEATHER] ");
    Serial.print(weatherCity);
    Serial.print(" | ");
    Serial.print(weatherTemperature, 1);
    Serial.print(" C | RH: ");
    Serial.print(weatherHumidity);
    Serial.print(" % | ");
    Serial.println(weatherCondition);

    return true;
}

// ============================================================
// OLED TITLE
// ============================================================

void oledTitle(
    const char* title
)
{
    display.clearDisplay();

    display.setTextColor(
        SSD1306_WHITE
    );

    // Prevent long lines from wrapping into the bottom area.
    display.setTextWrap(false);

    display.setTextSize(2);

    display.setCursor(
        0,
        0
    );

    display.println(title);

    display.drawLine(
        0,
        20,
        127,
        20,
        SSD1306_WHITE
    );
}

// ============================================================
// SHOW CURRENT PAGE
// ============================================================

void showPage()
{
    oledTitle(
        pages[currentPage]
    );

    display.setTextSize(1);
    display.setTextWrap(false);

    // --------------------------------------------------------
    // WIFI
    // --------------------------------------------------------

    if (currentPage == 0)
    {
        display.setCursor(0, 29);

        if (WiFi.status() == WL_CONNECTED)
        {
            display.println("Connected");

            display.print("RSSI: ");
            display.println(WiFi.RSSI());

            display.print("IP: ");
            display.println(WiFi.localIP());
        }
        else
        {
            display.println("Disconnected");
        }
    }

    // --------------------------------------------------------
    // WEATHER
    // --------------------------------------------------------

    else if (currentPage == 1)
    {
        display.setCursor(0, 28);

        if (isnan(weatherTemperature))
        {
            display.println("Loading weather...");
        }
        else
        {
            display.println(weatherCity);

            display.print(weatherTemperature, 1);
            display.println(" C");

            display.println(weatherCondition);

            display.print("RH: ");
            display.print(weatherHumidity);
            display.println(" %");
        }
    }

    // --------------------------------------------------------
    // ROOM
    // --------------------------------------------------------

    else if (currentPage == 2)
    {
        // Keep the lowest text well above the 64-pixel edge.
        display.setCursor(0, 29);
        display.println("Humidity");

        display.setCursor(0, 43);
        display.print("-- %");
    }

    // --------------------------------------------------------
    // SPOTIFY
    // --------------------------------------------------------

    else if (currentPage == 3)
    {
        display.setCursor(0, 29);
        display.println("Say: play <song>");

        display.setCursor(0, 42);
        display.println("pause / next / previous");

        display.setCursor(0, 52);
        display.println("Spotify -> iPhone");
    }

    display.display();
}

// ============================================================
// STATUS SCREEN
// ============================================================

void showStatus(
    const char* line1,
    const char* line2 = ""
)
{
    display.clearDisplay();

    display.setTextColor(
        SSD1306_WHITE
    );

    display.setTextWrap(false);

    display.setTextSize(2);

    display.setCursor(
        0,
        0
    );

    display.println(
        line1
    );

    display.setTextSize(1);

    display.setCursor(
        0,
        30
    );

    display.println(
        line2
    );

    display.display();
}

// ============================================================
// MEMORY DEBUG
// ============================================================

void printMemory(
    const char* label
)
{
    Serial.print(
        "[MEM] "
    );

    Serial.print(
        label
    );

    Serial.print(
        " | Free heap: "
    );

    Serial.print(
        ESP.getFreeHeap()
    );

    Serial.print(
        " | Min heap: "
    );

    Serial.println(
        ESP.getMinFreeHeap()
    );
}

// ============================================================
// I2S SETUP
// ============================================================

void setupI2S()
{
    i2s_config_t config = {

        .mode = (i2s_mode_t)(
            I2S_MODE_MASTER |
            I2S_MODE_RX |
            I2S_MODE_TX
        ),

        .sample_rate =
            MIC_SAMPLE_RATE,

        .bits_per_sample =
            I2S_BITS_PER_SAMPLE_32BIT,

        .channel_format =
            I2S_CHANNEL_FMT_ONLY_LEFT,

        .communication_format =
            I2S_COMM_FORMAT_STAND_I2S,

        .intr_alloc_flags =
            ESP_INTR_FLAG_LEVEL1,

        .dma_buf_count = 4,

        .dma_buf_len = 64,

        .use_apll = false,

        .tx_desc_auto_clear = true,

        .fixed_mclk = 0
    };

    i2s_pin_config_t pins = {

        .bck_io_num = I2S_BCLK,

        .ws_io_num = I2S_WS,

        .data_out_num =
            SPEAKER_DOUT,

        .data_in_num =
            MIC_DIN
    };

    i2s_driver_install(
        I2S_PORT,
        &config,
        0,
        NULL
    );

    i2s_set_pin(
        I2S_PORT,
        &pins
    );

    i2s_zero_dma_buffer(
        I2S_PORT
    );
}

// ============================================================
// WIFI
// ============================================================

bool connectWiFi()
{
    showStatus(
        "WIFI",
        "Connecting..."
    );

    Serial.println();
    Serial.println(
        "[WIFI] Connecting..."
    );

    WiFi.mode(
        WIFI_STA
    );

    // Keep this because it worked
    // well on your setup.

    WiFi.setTxPower(
        WIFI_POWER_8_5dBm
    );

    WiFi.setSleep(
        false
    );

    WiFi.setAutoReconnect(
        true
    );

    WiFi.begin(
        WIFI_SSID,
        WIFI_PASSWORD
    );

    uint32_t start =
        millis();

    while (
        WiFi.status() !=
            WL_CONNECTED &&
        millis() - start <
            20000
    )
    {
        delay(250);
        Serial.print(".");
    }

    Serial.println();

    if (
        WiFi.status() ==
        WL_CONNECTED
    )
    {
        Serial.println(
            "[WIFI] Connected"
        );

        Serial.print(
            "[WIFI] IP: "
        );

        Serial.println(
            WiFi.localIP()
        );

        Serial.print(
            "[WIFI] RSSI: "
        );

        Serial.println(
            WiFi.RSSI()
        );

        showPage();

        return true;
    }

    Serial.print(
        "[WIFI] Failed. Status: "
    );

    Serial.println(
        WiFi.status()
    );

    showStatus(
        "WIFI",
        "Connection failed"
    );

    return false;
}

// ============================================================
// WAV HEADER HELPERS
// ============================================================

void writeLE16(
    uint8_t* p,
    uint16_t value
)
{
    p[0] =
        value & 0xFF;

    p[1] =
        (value >> 8) & 0xFF;
}

void writeLE32(
    uint8_t* p,
    uint32_t value
)
{
    p[0] =
        value & 0xFF;

    p[1] =
        (value >> 8) & 0xFF;

    p[2] =
        (value >> 16) & 0xFF;

    p[3] =
        (value >> 24) & 0xFF;
}

// ============================================================
// CREATE WAV HEADER
// ============================================================

void createWavHeader(
    uint8_t* header,
    uint32_t dataBytes
)
{
    memset(
        header,
        0,
        44
    );

    memcpy(
        header + 0,
        "RIFF",
        4
    );

    writeLE32(
        header + 4,
        dataBytes + 36
    );

    memcpy(
        header + 8,
        "WAVE",
        4
    );

    memcpy(
        header + 12,
        "fmt ",
        4
    );

    writeLE32(
        header + 16,
        16
    );

    writeLE16(
        header + 20,
        1
    );

    writeLE16(
        header + 22,
        1
    );

    writeLE32(
        header + 24,
        MIC_SAMPLE_RATE
    );

    writeLE32(
        header + 28,
        MIC_SAMPLE_RATE * 2
    );

    writeLE16(
        header + 32,
        2
    );

    writeLE16(
        header + 34,
        16
    );

    memcpy(
        header + 36,
        "data",
        4
    );

    writeLE32(
        header + 40,
        dataBytes
    );
}

// ============================================================
// RECORD WHILE BUTTON IS HELD
// ============================================================

bool recordVoice(
    uint8_t buttonPin
)
{
    recordedSamples = 0;

    showStatus(
        "LISTEN",
        "Release button"
    );

    Serial.println();
    Serial.println(
        "[AUDIO] Listening..."
    );

    int32_t raw[64];

    uint32_t start =
        millis();

    while (
        digitalRead(buttonPin) ==
            LOW &&
        millis() - start <
            MAX_RECORD_SECONDS *
            1000UL
    )
    {
        size_t bytesRead = 0;

        esp_err_t result =
            i2s_read(
                I2S_PORT,
                raw,
                sizeof(raw),
                &bytesRead,
                portMAX_DELAY
            );

        if (
            result != ESP_OK
        )
        {
            Serial.println(
                "[AUDIO] I2S error"
            );

            return false;
        }

        int count =
            bytesRead /
            sizeof(int32_t);

        for (
            int i = 0;
            i < count;
            i++
        )
        {
            // INMP441 conversion
            int32_t sample =
                raw[i] >> 8;

            sample >>= 8;

            if (
                sample >
                32767
            )
            {
                sample = 32767;
            }

            if (
                sample <
                -32768
            )
            {
                sample = -32768;
            }

            if (
                recordedSamples <
                MAX_SAMPLES
            )
            {
                audioBuffer[
                    recordedSamples
                ] =
                    (int16_t)sample;

                recordedSamples++;
            }
        }
    }

    Serial.println();
    Serial.println(
        "[AUDIO] Recording finished"
    );

    Serial.print(
        "[AUDIO] Samples: "
    );

    Serial.println(
        recordedSamples
    );

    Serial.print(
        "[AUDIO] Duration: "
    );

    Serial.print(
        (float)recordedSamples /
        MIC_SAMPLE_RATE
    );

    Serial.println(
        " seconds"
    );

    if (
        recordedSamples <
        1600
    )
    {
        Serial.println(
            "[AUDIO] Too short"
        );

        return false;
    }

    printMemory(
        "After recording"
    );

    return true;
}

// ============================================================
// SEND WAV TO LAPTOP
// ============================================================

bool sendVoiceToServer()
{
    if (
        WiFi.status() !=
        WL_CONNECTED
    )
    {
        Serial.println(
            "[SERVER] WiFi lost"
        );

        return false;
    }

    showStatus(
        "THINK",
        "Talking to AI..."
    );

    uint8_t wavHeader[44];

    uint32_t audioBytes =
        recordedSamples *
        sizeof(int16_t);

    createWavHeader(
        wavHeader,
        audioBytes
    );

    uint32_t totalBytes =
        44 + audioBytes;

    Serial.println();
    Serial.println(
        "[SERVER] Connecting..."
    );

    WiFiClient client;

    if (
        !client.connect(
            SERVER_HOST,
            SERVER_PORT
        )
    )
    {
        Serial.println(
            "[SERVER] Connection failed"
        );

        return false;
    }

    // --------------------------------------------------------
    // HTTP REQUEST
    // --------------------------------------------------------

    client.print(
        "POST /voice HTTP/1.1\r\n"
    );

    client.print(
        "Host: "
    );

    client.print(
        SERVER_HOST
    );

    client.print(
        ":"
    );

    client.print(
        SERVER_PORT
    );

    client.print(
        "\r\n"
    );

    client.print(
        "Content-Type: audio/wav\r\n"
    );

    client.print(
        "Content-Length: "
    );

    client.print(
        totalBytes
    );

    client.print(
        "\r\n"
    );

    client.print(
        "Connection: close\r\n"
    );

    client.print(
        "\r\n"
    );

    // --------------------------------------------------------
    // WAV HEADER
    // --------------------------------------------------------

    client.write(
        wavHeader,
        sizeof(wavHeader)
    );

    // --------------------------------------------------------
    // AUDIO
    // --------------------------------------------------------

    const uint8_t* audio =
        (const uint8_t*)
        audioBuffer;

    size_t sent = 0;

    while (
        sent <
        audioBytes
    )
    {
        size_t chunk =
            1024;

        if (
            chunk >
            audioBytes - sent
        )
        {
            chunk =
                audioBytes - sent;
        }

        size_t written =
            client.write(
                audio + sent,
                chunk
            );

        if (
            written == 0
        )
        {
            Serial.println(
                "[SERVER] Send failed"
            );

            client.stop();

            return false;
        }

        sent += written;
    }

    Serial.println(
        "[SERVER] Audio sent"
    );

    // --------------------------------------------------------
    // WAIT FOR HTTP RESPONSE
    // --------------------------------------------------------

    uint32_t timeout =
        millis() + 60000;

    while (
        !client.available() &&
        client.connected()
    )
    {
        if (
            millis() >
            timeout
        )
        {
            Serial.println(
                "[SERVER] Response timeout"
            );

            client.stop();

            return false;
        }

        delay(5);
    }

    String statusLine =
        client.readStringUntil(
            '\n'
        );

    Serial.print(
        "[SERVER] "
    );

    Serial.println(
        statusLine
    );

    int statusCode = 0;

    int space =
        statusLine.indexOf(
            ' '
        );

    if (
        space >= 0
    )
    {
        statusCode =
            statusLine.substring(
                space + 1,
                space + 4
            ).toInt();
    }

    // --------------------------------------------------------
    // READ RESPONSE HEADERS
    // --------------------------------------------------------

    int contentLength = -1;

    while (
        client.connected()
    )
    {
        String line =
            client.readStringUntil(
                '\n'
            );

        line.trim();

        if (
            line.length() == 0
        )
        {
            break;
        }

        if (
            line.startsWith(
                "Content-Length:"
            )
        )
        {
            contentLength =
                line.substring(
                    15
                ).toInt();
        }
    }

    // --------------------------------------------------------
    // SERVER ERROR
    // --------------------------------------------------------

    if (
        statusCode != 200
    )
    {
        Serial.print(
            "[SERVER] HTTP error: "
        );

        Serial.println(
            statusCode
        );

        String errorText =
            client.readString();

        Serial.println(
            errorText
        );

        client.stop();

        showStatus(
            "ERROR",
            "Server error"
        );

        delay(1500);

        showPage();

        return false;
    }

    Serial.print(
        "[TTS] Length: "
    );

    Serial.println(
        contentLength
    );

    // --------------------------------------------------------
    // SWITCH I2S TO TTS
    // --------------------------------------------------------

    i2s_set_clk(
        I2S_PORT,
        TTS_SAMPLE_RATE,
        I2S_BITS_PER_SAMPLE_32BIT,
        I2S_CHANNEL_MONO
    );

    i2s_zero_dma_buffer(
        I2S_PORT
    );

    showStatus(
        "SPEAK",
        "AI voice"
    );

    printMemory(
        "Before TTS"
    );

    // --------------------------------------------------------
    // RECEIVE TTS PCM
    // --------------------------------------------------------

    uint8_t inputBuffer[512];

    int32_t outputBuffer[128];

    size_t outputCount = 0;

    uint8_t lowByte = 0;

    bool haveLowByte = false;

    size_t received = 0;

    while (
        client.connected() ||
        client.available()
    )
    {
        int availableBytes =
            client.available();

        if (
            availableBytes <= 0
        )
        {
            delay(2);
            continue;
        }

        int toRead =
            availableBytes;

        if (
            toRead >
            (int)sizeof(inputBuffer)
        )
        {
            toRead =
                sizeof(inputBuffer);
        }

        int n =
            client.read(
                inputBuffer,
                toRead
            );

        if (
            n <= 0
        )
        {
            continue;
        }

        received += n;

        for (
            int i = 0;
            i < n;
            i++
        )
        {
            uint8_t b =
                inputBuffer[i];

            if (
                !haveLowByte
            )
            {
                lowByte = b;
                haveLowByte = true;
            }
            else
            {
                int16_t pcm16 =
                    (int16_t)(
                        lowByte |
                        (
                            (uint16_t)b
                            << 8
                        )
                    );

                outputBuffer[
                    outputCount++
                ] =
                    ((int32_t)pcm16)
                    << 16;

                haveLowByte =
                    false;

                if (
                    outputCount >=
                    128
                )
                {
                    size_t written =
                        0;

                    i2s_write(
                        I2S_PORT,
                        outputBuffer,
                        outputCount *
                            sizeof(int32_t),
                        &written,
                        portMAX_DELAY
                    );

                    outputCount = 0;
                }
            }
        }
    }

    // --------------------------------------------------------
    // FLUSH REMAINING AUDIO
    // --------------------------------------------------------

    if (
        outputCount > 0
    )
    {
        size_t written = 0;

        i2s_write(
            I2S_PORT,
            outputBuffer,
            outputCount *
                sizeof(int32_t),
            &written,
            portMAX_DELAY
        );
    }

    client.stop();

    i2s_zero_dma_buffer(
        I2S_PORT
    );

    Serial.print(
        "[TTS] Received: "
    );

    Serial.println(
        received
    );

    printMemory(
        "After TTS"
    );

    showPage();

    return true;
}

// ============================================================
// BUTTON HANDLER
// ============================================================

void handleButton(
    uint8_t pin,
    bool next
)
{
    if (
        digitalRead(pin) != LOW
    )
    {
        return;
    }

    uint32_t pressStart =
        millis();

    // Wait for release OR long press
    while (
        digitalRead(pin) == LOW
    )
    {
        if (
            millis() -
                pressStart >=
            LONG_PRESS_MS
        )
        {
            // ------------------------------------------------
            // LONG PRESS = PUSH TO TALK
            // ------------------------------------------------

            bool success =
                recordVoice(pin);

            while (
                digitalRead(pin) ==
                LOW
            )
            {
                delay(5);
            }

            if (
                success
            )
            {
                sendVoiceToServer();
            }

            return;
        }

        delay(5);
    }

    // --------------------------------------------------------
    // SHORT PRESS
    // --------------------------------------------------------

    if (
        millis() -
            pressStart <
        LONG_PRESS_MS
    )
    {
        if (next)
        {
            currentPage++;

            if (
                currentPage >=
                PAGE_COUNT
            )
            {
                currentPage = 0;
            }
        }
        else
        {
            currentPage--;

            if (
                currentPage < 0
            )
            {
                currentPage =
                    PAGE_COUNT - 1;
            }
        }

        if (currentPage == 1)
        {
            if (isnan(weatherTemperature) ||
                millis() - lastWeatherUpdate >=
                    WEATHER_UPDATE_INTERVAL)
            {
                updateWeather();
            }
        }

        showPage();

        delay(80);
    }
}

// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(
        115200
    );

    delay(1000);

    Serial.println();
    Serial.println(
        "================================"
    );
    Serial.println(
        "ESP32-C3 AI ASSISTANT"
    );
    Serial.println(
        "================================"
    );

    // Buttons
    pinMode(
        BUTTON_NEXT,
        INPUT_PULLUP
    );

    pinMode(
        BUTTON_PREV,
        INPUT_PULLUP
    );

    // OLED
    Wire.begin(
        21,
        20
    );

    if (
        !display.begin(
            SSD1306_SWITCHCAPVCC,
            OLED_ADDR
        )
    )
    {
        Serial.println(
            "OLED failed!"
        );

        while (true)
        {
            delay(100);
        }
    }

    // I2S
    setupI2S();

    showStatus(
        "AI",
        "AI-generated voice"
    );

    delay(1500);

    // Wi-Fi
    connectWiFi();

    if (WiFi.status() == WL_CONNECTED)
    {
        updateWeather();
    }

    printMemory(
        "Startup"
    );

    showPage();
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    // --------------------------------------------------------
    // AUTOMATIC WIFI RECOVERY
    // --------------------------------------------------------

    if (
        WiFi.status() !=
        WL_CONNECTED
    )
    {
        connectWiFi();

        delay(500);

        return;
    }

    // --------------------------------------------------------
    // WEATHER REFRESH
    // --------------------------------------------------------

    if (millis() - lastWeatherUpdate >=
        WEATHER_UPDATE_INTERVAL)
    {
        updateWeather();
    }

    // --------------------------------------------------------
    // BUTTONS
    // --------------------------------------------------------

    handleButton(
        BUTTON_NEXT,
        true
    );

    handleButton(
        BUTTON_PREV,
        false
    );

    delay(5);
}