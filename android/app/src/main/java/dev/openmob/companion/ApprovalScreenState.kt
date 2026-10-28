package dev.openmob.companion

/**
 * What the approval screen shows for one request, computed once and drawn by either UI (the original views or the
 * redesign's Compose screen: docs/design/redesign-approval.md). This is ApprovalActivity.render's own logic, moved
 * here unchanged so both UIs show the same thing; it decides nothing about approving.
 */
data class ApprovalScreenState(
    /** The request is still pending (not answered, not expired). */
    val open: Boolean,
    /** A request was found for this id at some point (shown after it's answered, to keep showing it). */
    val known: Boolean,
    val label: String,
    /** The phone's own words where it has them (Approvals.Request.shownQuestion), else "already answered…". */
    val question: String,
    val explain: String,
    val gate: Boolean,
    /** A gate prompt's level: "tap" (Allow, no lock) or "fingerprint". */
    val level: String,
    val kind: String,
    val alwaysVisible: Boolean,
    val alwaysText: String,
    /** The original screen's line: "Server says: “…”" (gate) or "Asked by …" (server-supplied, labelled). */
    val requesterLine: String,
    /** Server-supplied, shown only labelled as the server's. */
    val requester: String,
    /** Server-supplied, shown only labelled as the server's ("not checked by the phone"). */
    val serverSays: String,
    val crop: ByteArray?,
    /** Built on the phone from the action's own fields (what the signature binds); "" if none. */
    val actionLine: String,
    /** Why it can't be approved here (only denied), or null. */
    val blocker: String?,
    val denyEnabled: Boolean,
    val approveEnabled: Boolean,
    val approveVisible: Boolean,
    /** Uptime ms when it expires unanswered (Approvals.Request.expiresAt), or 0 if unknown: the countdown. */
    val expiresAt: Long = 0,
    /** The task's request text, only when the owner typed it on this phone (GateHost.attestedTaskText, typedHere):
     *  drawn under "Checked by this phone". Never server text. */
    val taskText: String? = null,
    /** The task's request text held because the owner approved a task grant for it here: the server worded it, so it
     *  is drawn outside "Checked by this phone", labelled as the server's wording (review 3, P3-M1). */
    val grantTaskText: String? = null,
    /** A money prompt whose own wording shows no amount: the screen says the amount wasn't checked (display only). */
    val amountUnchecked: Boolean = false,
) {
    companion object {
        /** [str] is Context.getString; [appLabel] the package's label. Same branches as the original render. */
        fun of(
            request: Approvals.Request?,
            open: Boolean,
            str: (Int, Array<out Any>) -> String,
            appLabel: (String) -> String,
            /** The task text the owner typed on this phone (gate prompts only); null: none, and nothing is shown. */
            taskText: String? = null,
            /** The task text a task grant approved here holds (gate prompts only), worded by the server. */
            grantTaskText: String? = null,
        ): ApprovalScreenState {
            fun s(id: Int, vararg a: Any) = str(id, a)
            val kind = request?.kind ?: "action"
            // Faster mode (UX review 2, H6): its own words and the required warning, not "agents would ask you less".
            val input = request?.action?.get("input").orEmpty()
            val faster = kind == "mode_change" && dev.openmob.companion.gate.ModeChange.fasterScope(input) != null
            val always = request?.always
            val blocker = request?.let { blocker(it, ::s) }
            return ApprovalScreenState(
                open = open,
                known = request != null,
                label = s(when (kind) {
                    "mode_change" -> R.string.approval_label_mode
                    "plan" -> R.string.approval_label_plan
                    "step" -> R.string.approval_label_step
                    else -> R.string.approval_label
                }),
                question = request?.shownQuestion ?: s(R.string.approval_gone),
                explain = s(when {
                    faster -> R.string.faster_warning
                    request?.allowsMoney == true -> R.string.approval_explain_mode_money
                    request?.gate == true -> R.string.gate_explain
                    kind == "mode_change" -> R.string.approval_explain_mode
                    kind == "plan" -> R.string.approval_explain_plan
                    else -> R.string.approval_explain
                }),
                gate = request?.gate == true,
                level = request?.level ?: "fingerprint",
                kind = kind,
                alwaysVisible = always != null && open,
                alwaysText = if (always == null) "" else (if (always.kind == "permission") s(R.string.gate_always_for, appLabel(always.app))
                    else s(R.string.approval_always)) + "\n${always.text}",
                requesterLine = request?.let {
                    if (it.gate) (if (it.serverSays.isEmpty()) "" else s(R.string.gate_server_says, it.serverSays))
                    else s(R.string.approval_requester, it.requester)
                }.orEmpty(),
                requester = if (request?.gate == false) request.requester else "",
                serverSays = request?.serverSays.orEmpty(),
                crop = request?.crop,
                // Phone-built only (it is drawn under "Checked by this phone"): a permission change from its parsed input.
                actionLine = request?.actionLine.orEmpty(),
                blocker = blocker,
                denyEnabled = open,
                // A phone that can't sign this approval can only deny it.
                approveEnabled = open && blocker == null,
                approveVisible = blocker == null,
                expiresAt = request?.expiresAt ?: 0,
                taskText = taskText?.takeIf { request?.gate == true && it.isNotBlank() },
                grantTaskText = grantTaskText?.takeIf { request?.gate == true && it.isNotBlank() && taskText.isNullOrBlank() },
                amountUnchecked = request != null && amountUnchecked(request),
            )
        }

        private val MONEY = Regex("""(?i)\b(buy|pay|purchase|checkout|check out|order|subscribe|donate|send money|transfer|tip)\b""")
        private val AMOUNT = Regex("""[$€£¥₹]\s?\d|\d[\d,.]*\s?(usd|eur|gbp|dollars?)\b|\d+[.,]\d{2}\b""", RegexOption.IGNORE_CASE)

        /** A screen-lock gate prompt that reads as money (its own wording) but shows no amount. Display only. */
        fun amountUnchecked(r: Approvals.Request): Boolean =
            r.gate && r.level == "fingerprint" && MONEY.containsMatchIn(r.question) && !AMOUNT.containsMatchIn(r.question)

        /** Why this request can't be approved on this phone (it can still be denied), or null. */
        fun blocker(request: Approvals.Request, s: (Int, Array<out Any>) -> String): String? = when {
            !request.canApprove -> request.cannotApproveReason.ifEmpty { s(R.string.approval_cannot, emptyArray()) }
            // The action shown must be the action signed: a request whose digest doesn't match its own
            // fields is malformed (or lying), so it can't be approved.
            request.digest.isNotEmpty() && !request.consistent -> s(R.string.approval_mismatch, emptyArray())
            request.signatureRequired && request.digest.isEmpty() -> s(R.string.approval_mismatch, emptyArray())
            else -> null
        }
    }
}
