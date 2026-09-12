import { useEffect, useRef, useCallback, useState } from "react";
import { BASE } from "../api/base";

interface WSMessage {
  type: string;
  data?: any;
  codes?: string[];
  time?: string;
  account?: any;
}

export function useWebSocket(url: string) {
  const wsRef = useRef<WebSocket | null>(null);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimer = useRef<number>(0);
  const subscribedCodesRef = useRef<string[]>([]);

  const flushSubscription = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    if (subscribedCodesRef.current.length > 0) {
      wsRef.current.send(
        JSON.stringify({ type: "subscribe", codes: subscribedCodesRef.current })
      );
    }
  }, []);

  const connect = useCallback(() => {
    try {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      let wsUrl: string;
      
      if (url.startsWith("ws")) {
        wsUrl = url;
      } else if (import.meta.env.DEV) {
        wsUrl = `ws://localhost:8000${url}`;
      } else {
        wsUrl = `${protocol}//${window.location.host}${BASE}${url}`;
      }
      
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setConnected(true);
        flushSubscription();
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          setLastMessage(msg);
        } catch {
          // ignore
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectTimer.current = window.setTimeout(() => {
          connect();
        }, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    } catch {
      reconnectTimer.current = window.setTimeout(() => {
        connect();
      }, 3000);
    }
  }, [flushSubscription, url]);

  const subscribe = useCallback((codes: string[]) => {
    subscribedCodesRef.current = codes;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "subscribe", codes }));
    }
  }, []);

  const unsubscribe = useCallback(() => {
    subscribedCodesRef.current = [];
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "unsubscribe" }));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { lastMessage, connected, subscribe, unsubscribe };
}
