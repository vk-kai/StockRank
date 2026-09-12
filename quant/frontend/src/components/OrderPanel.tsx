import { useState } from "react";
import { placeOrder } from "../api";

interface Props {
  code: string;
  name: string;
  currentPrice: number;
  onOrderComplete: () => void;
}

export default function OrderPanel({ code, name, currentPrice, onOrderComplete }: Props) {
  const [direction, setDirection] = useState<"buy" | "sell">("buy");
  const [price, setPrice] = useState<string>(currentPrice ? currentPrice.toFixed(3) : "");
  const [quantity, setQuantity] = useState<string>("1000");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const handlePriceChange = (val: string) => {
    setPrice(val);
  };

  const handleQuantityChange = (val: string) => {
    setQuantity(val);
  };

  const setQuickQuantity = (pct: number) => {
    setMessage("");
  };

  const fillCurrentPrice = () => {
    if (currentPrice) {
      setPrice(currentPrice.toFixed(3));
    }
  };

  const handleSubmit = async () => {
    const p = parseFloat(price);
    const q = parseInt(quantity);
    if (isNaN(p) || isNaN(q) || p <= 0 || q <= 0) {
      setMessage("请输入有效的价格和数量");
      return;
    }
    if (q % 100 !== 0) {
      setMessage("数量必须为100的整数倍");
      return;
    }

    setLoading(true);
    setMessage("");
    try {
      const result = await placeOrder(code, direction, p, q);
      if (result.success) {
        setMessage(`${direction === "buy" ? "买入" : "卖出"}成功!`);
        onOrderComplete();
      } else {
        setMessage(result.message || "下单失败");
      }
    } catch (e: any) {
      setMessage("下单请求失败: " + e.message);
    }
    setLoading(false);
  };

  const totalAmount = parseFloat(price || "0") * parseInt(quantity || "0");

  return (
    <div className="order-panel">
      <h3>模拟下单</h3>
      <div className="order-info">
        <span className="order-code">{code}</span>
        <span className="order-name">{name}</span>
      </div>

      <div className="direction-tabs">
        <button
          className={`direction-btn buy ${direction === "buy" ? "active" : ""}`}
          onClick={() => { setDirection("buy"); setMessage(""); }}
        >
          买入
        </button>
        <button
          className={`direction-btn sell ${direction === "sell" ? "active" : ""}`}
          onClick={() => { setDirection("sell"); setMessage(""); }}
        >
          卖出
        </button>
      </div>

      <div className="order-field">
        <label>价格</label>
        <div className="price-input-wrap">
          <input
            type="number"
            step="0.001"
            value={price}
            onChange={(e) => handlePriceChange(e.target.value)}
            className="order-input"
          />
          <button className="fill-price-btn" onClick={fillCurrentPrice}>
            现价
          </button>
        </div>
      </div>

      <div className="order-field">
        <label>数量(股)</label>
        <input
          type="number"
          step="100"
          value={quantity}
          onChange={(e) => handleQuantityChange(e.target.value)}
          className="order-input"
        />
        <div className="quick-qty">
          <button onClick={() => setQuantity("100")}>100</button>
          <button onClick={() => setQuantity("500")}>500</button>
          <button onClick={() => setQuantity("1000")}>1k</button>
          <button onClick={() => setQuantity("5000")}>5k</button>
          <button onClick={() => setQuantity("10000")}>1w</button>
        </div>
      </div>

      <div className="order-summary">
        <div className="summary-row">
          <span>预估金额</span>
          <span>{isNaN(totalAmount) ? "--" : totalAmount.toFixed(2)}</span>
        </div>
      </div>

      <button
        className={`submit-btn ${direction}`}
        onClick={handleSubmit}
        disabled={loading}
      >
        {loading ? "提交中..." : direction === "buy" ? "确认买入" : "确认卖出"}
      </button>

      {message && (
        <div className={`order-message ${message.includes("成功") ? "success" : "error"}`}>
          {message}
        </div>
      )}
    </div>
  );
}
