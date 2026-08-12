export interface RiskParameters {
  accountBalance: number;       // Balance total de la cuenta en USDT / VST
  riskPercentage: number;       // % de la cuenta a arriesgar, como número ENTERO (ej. 2% se pasa como 2.0, NO como 0.02)
  entryPrice: number;           // Precio de entrada
  stopLossPrice: number;        // Precio de Stop Loss
  takeProfitPrice?: number;     // Precio de Take Profit (opcional)
  leverage: number;             // Apalancamiento (ej. 10x)
  positionSide: 'LONG' | 'SHORT';
}

export interface RiskCalculationResult {
  maxRiskAmountUSDT: number;   // Pérdida máxima tolerada en USDT
  positionSizeCoins: number;   // Cantidad de monedas a comprar/vender
  positionValueUSDT: number;   // Valor total de la posición (Notional Value)
  marginRequiredUSDT: number;  // Margen requerido de la cuenta
  riskRewardRatio: number;     // Ratio Riesgo:Beneficio (ej. 1:2.5)
  expectedProfitUSDT: number;  // Beneficio esperado al llegar al Take Profit
  stopLossPercent: number;     // % de variación del precio para llegar al SL
  takeProfitPercent: number;   // % de variación del precio para llegar al TP
  isRiskAcceptable: boolean;   // Booleano indicando si el margen no supera el disponible
  recommendation: string;
}

export class RiskCalculator {
  static calculate(params: RiskParameters): RiskCalculationResult {
    const {
      accountBalance,
      riskPercentage,
      entryPrice,
      stopLossPrice,
      takeProfitPrice,
      leverage,
      positionSide,
    } = params;

    // 1. Pérdida máxima en USDT basada en el % de riesgo.
    // `riskPercentage` se trata como número entero (2.0 = 2%), acorde a como lo
    // llama auto-bot.ts (`riskPerTradePercent: 2.0`). Si en algún momento se
    // cambia esta convención, hay que actualizar TANTO este cálculo como todos
    // los callers a la vez — de lo contrario el riesgo real por trade queda
    // desalineado del riesgo configurado (ej. si alguien "corrige" el caller
    // para pasar 0.02 pensando que es decimal, el riesgo real caería 100x sin
    // que nadie lo note hasta revisar el PnL).
    const maxRiskAmountUSDT = accountBalance * (riskPercentage / 100);

    // 2. Distancia porcentual al Stop Loss
    const stopLossDistance = Math.abs(entryPrice - stopLossPrice);
    const stopLossPercent = (stopLossDistance / entryPrice) * 100;

    // 3. Cantidad de monedas a operar para que al tocar el SL la pérdida sea EXACTAMENTE el % de riesgo deseado
    let positionSizeCoins = 0;
    if (stopLossDistance > 0) {
      positionSizeCoins = maxRiskAmountUSDT / stopLossDistance;
    }

    // 4. Notional Value y Margen Requerido
    const positionValueUSDT = positionSizeCoins * entryPrice;
    const marginRequiredUSDT = positionValueUSDT / leverage;

    // 5. Take Profit y Ratio Riesgo/Beneficio
    let expectedProfitUSDT = 0;
    let takeProfitPercent = 0;
    let riskRewardRatio = 0;

    if (takeProfitPrice && takeProfitPrice > 0) {
      const takeProfitDistance = Math.abs(takeProfitPrice - entryPrice);
      takeProfitPercent = (takeProfitDistance / entryPrice) * 100;
      expectedProfitUSDT = positionSizeCoins * takeProfitDistance;
      riskRewardRatio = parseFloat((expectedProfitUSDT / (maxRiskAmountUSDT || 1)).toFixed(2));
    }

    const isRiskAcceptable = marginRequiredUSDT <= accountBalance;
    let recommendation = `Gestión correcta. Arriesgando $${maxRiskAmountUSDT.toFixed(2)} (${riskPercentage}% de la cuenta). Margen requerido: $${marginRequiredUSDT.toFixed(2)}`;

    if (!isRiskAcceptable) {
      recommendation = `⚠️ Alerta: El margen requerido ($${marginRequiredUSDT.toFixed(2)}) supera el saldo de tu cuenta ($${accountBalance.toFixed(2)}). Reduce el apalancamiento o ajusta el Stop Loss.`;
    } else if (riskRewardRatio > 0 && riskRewardRatio < 1.5) {
      recommendation = `⚠️ Advertencia: El Ratio Riesgo/Beneficio es bajo (${riskRewardRatio}:1). Se recomienda un ratio mínimo de 1:1.5 o 1:2.`;
    }

    return {
      maxRiskAmountUSDT: parseFloat(maxRiskAmountUSDT.toFixed(2)),
      positionSizeCoins: parseFloat(positionSizeCoins.toFixed(4)),
      positionValueUSDT: parseFloat(positionValueUSDT.toFixed(2)),
      marginRequiredUSDT: parseFloat(marginRequiredUSDT.toFixed(2)),
      riskRewardRatio,
      expectedProfitUSDT: parseFloat(expectedProfitUSDT.toFixed(2)),
      stopLossPercent: parseFloat(stopLossPercent.toFixed(2)),
      takeProfitPercent: parseFloat(takeProfitPercent.toFixed(2)),
      isRiskAcceptable,
      recommendation,
    };
  }
}