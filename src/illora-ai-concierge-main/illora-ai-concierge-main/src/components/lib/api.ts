// src/lib/api.ts
export async function sendMessage(message: string) {
  try {
    const response = await fetch("http://localhost:5002/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("sendMessage error:", error);
    throw error;
  }
}
