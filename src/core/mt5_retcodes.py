"""Plain-English translation of MT5 order return codes.

A bare "retcode 10017" in the log tells the user nothing. Every rejection the bot
can hit is mapped here to what actually went wrong and what to do about it, so the
log answers "why won't it trade?" without the user having to look up MT5 docs.
"""

# retcode -> (short reason, what the user should do about it)
RETCODES = {
    10004: ("Requote", "Price moved before the order landed. Usually harmless -- raise slippage_points if it keeps happening."),
    10006: ("Rejected by broker", "The broker refused the order outright. Check the MT5 Journal tab for the broker's reason."),
    10007: ("Cancelled by trader", "The order was cancelled manually."),
    10008: ("Order placed", "Order accepted but not yet filled."),
    10009: ("Done", "Order completed successfully."),
    10010: ("Partially filled", "Only part of the requested volume was filled."),
    10011: ("Request processing error", "MT5 could not process the request. Restart the terminal if it repeats."),
    10012: ("Request timed out", "The broker did not answer in time. Check your internet connection."),
    10013: ("Invalid request", "The order request was malformed -- this is a bot bug, please report it with the log line."),
    10014: ("Invalid volume", "The lot size is not allowed for this symbol. Lower risk_percent, or check the symbol's min/max lot with your broker."),
    10015: ("Invalid price", "The order price is not valid for this symbol right now."),
    10016: ("Invalid stops", "Stop loss / take profit are too close to the current price. Increase the SL/TP multiples in strategy settings."),
    10017: ("Trading is DISABLED", "Turn ON the 'Algo Trading' button in the MT5 terminal toolbar. Also check: the symbol is enabled in Market Watch, and you are NOT logged in with an investor (read-only) password."),
    10018: ("Market is closed", "This symbol is not tradeable right now. Wait for the session to open."),
    10019: ("Not enough money", "The account does not have enough free margin for this lot size. Lower risk_percent."),
    10020: ("Prices changed", "Price moved during processing. Usually harmless."),
    10021: ("No quotes to process", "The broker is not sending prices for this symbol. Check it is enabled in Market Watch."),
    10022: ("Invalid order expiration", "The expiration date on the order is not accepted by the broker."),
    10023: ("Order state changed", "The order changed while being processed. Usually harmless."),
    10024: ("Too many requests", "The bot is sending orders too fast. Increase the engine tick interval."),
    10025: ("No changes in request", "The requested SL/TP is identical to what is already set."),
    10026: ("Autotrading disabled by server", "The BROKER has disabled automated trading on this account. Contact your broker."),
    10027: ("Autotrading disabled by client", "Turn ON the 'Algo Trading' button in the MT5 terminal toolbar."),
    10028: ("Request locked for processing", "The request is already being processed."),
    10029: ("Order or position frozen", "The broker has frozen this order/position, usually near expiry. Try again later."),
    10030: ("Unsupported fill mode", "The broker does not accept this order filling mode -- this is a bot bug, please report it."),
    10031: ("No connection", "No connection to the trade server. Check the MT5 terminal is logged in."),
    10032: ("Live accounts only", "This operation is only allowed on live accounts."),
    10033: ("Pending order limit reached", "You have hit the broker's maximum number of pending orders."),
    10034: ("Volume limit reached", "You have hit the broker's maximum total volume for this symbol."),
    10035: ("Invalid or prohibited order type", "The broker does not allow this order type."),
    10036: ("Position already closed", "The position no longer exists."),
    10038: ("Close volume exceeds position", "Tried to close more lots than the position holds."),
    10039: ("Close order already exists", "A close order for this position is already pending."),
    10040: ("Too many open positions", "The account has hit the broker's maximum number of open positions."),
    10041: ("Close-by request rejected", "The broker rejected the close-by request."),
    10042: ("Long positions only", "The broker only allows BUY positions on this symbol right now."),
    10043: ("Short positions only", "The broker only allows SELL positions on this symbol right now."),
    10044: ("Closing only", "The broker only allows closing positions on this symbol right now."),
}


def explain(retcode):
    """Return 'Short reason -- what to do' for an MT5 retcode. Unknown codes still
    return something useful rather than swallowing the number."""
    try:
        code = int(retcode)
    except (TypeError, ValueError):
        return f"{retcode}"
    reason, fix = RETCODES.get(code, ("Unknown broker error", "Check the MT5 terminal's Journal tab for details."))
    return f"{reason} (retcode {code}) -- {fix}"
