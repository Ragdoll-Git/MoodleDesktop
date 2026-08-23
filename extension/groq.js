// groq.js - Actualizado a Qwen 3.6 27B
export async function askGroq(question, base64Image, apiKey) {
    const url = "https://api.groq.com/openai/v1/chat/completions";

    const payload = {
        // Qwen 3.6 27B - Soporta visión, rápido en Groq
        model: "qwen/qwen3.6-27b",
        messages: [
            {
                role: "user",
                content: [
                    { type: "text", text: question },
                    { type: "image_url", image_url: { url: `data:image/png;base64,${base64Image}` } }
                ]
            }
        ],
        temperature: 0.27,
        max_tokens: 4000
    };

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${apiKey.replace(/[^\x00-\x7F]/g, "").trim()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            // Mejora: Mostramos el código de error para debug (ej: model_decommissioned)
            throw new Error(errorData.error?.message || `Groq Error ${errorData.error?.code || response.status}`);
        }

        const result = await response.json();
        const answer = result.choices[0]?.message?.content;

        if (!answer) throw new Error("Respuesta vacía de Groq");

        return { success: true, text: answer, model: "Qwen 3.6 27B" };

    } catch (error) {
        console.error("Error en Groq Service:", error);
        return { success: false, error: error.message };
    }
}