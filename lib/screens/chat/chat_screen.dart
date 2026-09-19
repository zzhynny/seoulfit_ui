import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../data/repositories/chat_repository.dart';
import '../../models/chat.dart';
import '../../models/companion.dart';
import '../../widgets/animations.dart';
import 'date_range_answer.dart';
import '../../providers/companion_provider.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';

enum ChatMode { plan, onTrip }

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.onOpenHelpTopic,
    required this.onBuildItinerary,
    required this.onOpenDayPlanner,
  });

  final void Function(LiveHelpTopic topic) onOpenHelpTopic;
  final VoidCallback onBuildItinerary;

  /// Opens the Day Planner screen — the `day_plan` step's CTA, shown instead
  /// of "Ready? Build My Itinerary" while the backend is waiting on the
  /// per-day area/focus rows rather than a yes.
  final VoidCallback onOpenDayPlanner;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  ChatMode _mode = ChatMode.plan;
  List<ChatMessage> _messages = [];

  /// A real turn takes seconds against Gemini. Without this, tapping a quick
  /// reply twice sends two turns and the second answer lands on a question
  /// the backend has already moved past.
  bool _sending = false;

  /// The "In Seoul now?" card was closed. Per session only: it comes back next
  /// launch, since the whole point is that people don't find this mode.
  bool _onTripHintDismissed = false;
  final _composerController = TextEditingController();
  int _travelerCount = 2;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final messages = await context.read<ChatRepository>().fetchConversation();
      if (!mounted) return;
      setState(() => _messages = messages);
    } catch (_) {
      // Unhandled before: a timed-out/failed initial fetch left _messages at
      // [] with no error and no way back — the chat just opens empty and
      // silent, forever, instead of a visible spinner, but same root cause
      // (server unreachable) as the Lens/day-planner bugs.
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text("Couldn't reach the server."),
            action: SnackBarAction(label: 'Retry', onPressed: _load),
          ),
        );
      }
    }
  }

  Future<void> _pickDates() async {
    final answer = await pickTravelDates(context);
    if (answer != null) await _send(answer);
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _composerController.text).trim();
    if (text.isEmpty || _sending) return;
    setState(() {
      _sending = true;
      _messages = [..._messages, ChatMessage(sender: ChatSender.user, text: text)];
      _composerController.clear();
    });
    try {
      final reply = await context.read<ChatRepository>().sendMessage(text);
      if (!mounted) return;
      setState(() => _messages = [..._messages, reply]);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  void dispose() {
    _composerController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    // Nullable lookup: some test harnesses mount the chat without a trip.
    final hasPlan = context.watch<TripProvider?>()?.hasItinerary ?? false;
    return Column(
      children: [
        _buildHeader(companion),
        Expanded(
          child: _mode == ChatMode.plan
              ? _PlanView(
                  messages: _messages,
                  companion: companion,
                  travelerCount: _travelerCount,
                  onTravelerChange: (v) => setState(() => _travelerCount = v),
                  composerController: _composerController,
                  sending: _sending,
                  onSend: _send,
                  onQuickReply: _send,
                  onPickDates: _pickDates,
                  onBuildItinerary: widget.onBuildItinerary,
                  onOpenDayPlanner: widget.onOpenDayPlanner,
                  // Once there is a plan the traveller is on their way, and
                  // that's when on-trip help matters -- so surface it here
                  // instead of relying on the header toggle being found.
                  onTripHint: hasPlan && !_onTripHintDismissed
                      ? _OnTripHint(
                          onOpenTopic: widget.onOpenHelpTopic,
                          onShowAll: () =>
                              setState(() => _mode = ChatMode.onTrip),
                          onDismiss: () =>
                              setState(() => _onTripHintDismissed = true),
                        )
                      : null,
                )
              : _OnTripView(onOpenTopic: widget.onOpenHelpTopic),
        ),
      ],
    );
  }

  Widget _buildHeader(Companion companion) {
    return Container(
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          // Flexible + ellipsis: the title gives way, never the toggle. On a
          // 360px phone the two only just fit, and a larger system text size
          // overflowed the row.
          if (_mode == ChatMode.plan)
            Flexible(
              child: Row(
                children: [
                  SizedBox(
                    width: 36,
                    height: 36,
                    child: Image.asset(companion.guideChatAsset, fit: BoxFit.contain),
                  ),
                  const SizedBox(width: 12),
                  Flexible(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('SeoulFit AI',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTextStyles.headingSmall.copyWith(fontSize: 16)),
                        Row(
                          children: [
                            Container(
                              width: 6,
                              height: 6,
                              decoration: const BoxDecoration(
                                color: AppColors.primary,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 4),
                            Flexible(
                              child: Text('Online Concierge',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: AppTextStyles.caption),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            )
          else
            const Spacer(),
          _ModeToggle(mode: _mode, onChanged: (m) => setState(() => _mode = m)),
        ],
      ),
    );
  }
}

class _ModeToggle extends StatelessWidget {
  const _ModeToggle({required this.mode, required this.onChanged});

  final ChatMode mode;
  final ValueChanged<ChatMode> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.border,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          _pill(context, 'Plan', Icons.chat_bubble_outline, ChatMode.plan),
          const SizedBox(width: 3),
          _pill(context, 'On-trip', Icons.explore_outlined, ChatMode.onTrip),
        ],
      ),
    );
  }

  // Was 11px grey-on-grey with no icon: the unselected "On-trip" read as a
  // label, not a button, and testers never found the on-trip help behind it.
  // The unselected pill is now a white button of its own.
  Widget _pill(
      BuildContext context, String label, IconData icon, ChatMode value) {
    final selected = mode == value;
    final fg = selected ? Colors.white : AppColors.textPrimary;
    return Semantics(
      button: true,
      selected: selected,
      label: value == ChatMode.onTrip ? 'On-trip help' : 'Plan chat',
      excludeSemantics: true,
      child: GestureDetector(
        onTap: () => onChanged(value),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: selected ? AppColors.textPrimary : Colors.white,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 14, color: fg),
              const SizedBox(width: 4),
              Text(
                label,
                style: AppTextStyles.bodySmall
                    .copyWith(color: fg, fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PlanView extends StatelessWidget {
  const _PlanView({
    required this.messages,
    required this.companion,
    required this.travelerCount,
    required this.onTravelerChange,
    required this.composerController,
    required this.onSend,
    required this.onBuildItinerary,
    required this.onQuickReply,
    required this.onPickDates,
    required this.sending,
    required this.onOpenDayPlanner,
    this.onTripHint,
  });

  final List<ChatMessage> messages;
  final Companion companion;
  final int travelerCount;
  final ValueChanged<int> onTravelerChange;
  final TextEditingController composerController;
  final VoidCallback onSend;
  final VoidCallback onBuildItinerary;
  final ValueChanged<String> onQuickReply;
  final VoidCallback onPickDates;
  final VoidCallback onOpenDayPlanner;

  /// Shortcut card into on-trip help, under the messages. Null hides it.
  final Widget? onTripHint;

  /// A turn is in flight. Shown as a typing bubble, and the composer's send
  /// button becomes a spinner.
  final bool sending;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.all(24),
            itemCount: messages.length,
            separatorBuilder: (_, _) => const SizedBox(height: 16),
            itemBuilder: (context, index) {
              final message = messages[index];
              if (message.sender == ChatSender.user) {
                return Align(
                  alignment: Alignment.centerRight,
                  child: Container(
                    constraints: const BoxConstraints(maxWidth: 280),
                    padding: const EdgeInsets.all(16),
                    decoration: const BoxDecoration(
                      color: AppColors.bubbleUser,
                      borderRadius: BorderRadius.only(
                        topLeft: Radius.circular(20),
                        topRight: Radius.circular(20),
                        bottomLeft: Radius.circular(20),
                        bottomRight: Radius.circular(4),
                      ),
                    ),
                    child: Text(
                      message.text,
                      style: AppTextStyles.bodyMedium.copyWith(color: Colors.white),
                    ),
                  ),
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  SizedBox(
                    width: 38,
                    height: 38,
                    child: Image.asset(companion.guideChatAsset, fit: BoxFit.contain),
                  ),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Container(
                      constraints: const BoxConstraints(maxWidth: 260),
                      padding: const EdgeInsets.all(16),
                      decoration: const BoxDecoration(
                        color: AppColors.bubbleBot,
                        borderRadius: BorderRadius.only(
                          topLeft: Radius.circular(20),
                          topRight: Radius.circular(20),
                          bottomRight: Radius.circular(20),
                          bottomLeft: Radius.circular(4),
                        ),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(message.text, style: AppTextStyles.bodyMedium),
                          if (message.showTravelerSelector) ...[
                            const SizedBox(height: 12),
                            _TravelerSelector(count: travelerCount, onChange: onTravelerChange),
                          ],
                        ],
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
        ?onTripHint,
        // day_plan 단계에서는 일정 생성 대신 Day Planner 로 보낸다.
        if (messages.isNotEmpty && messages.last.awaitingStep == 'day_plan')
          _CtaButton(
            label: 'Plan each day',
            onPressed: onOpenDayPlanner,
          ),
        // Must check only the LAST message, not `.any` over history: a
        // confirm-stage edit that changes trip length bounces current_step
        // back to day_plan, appending a new message whose readyToBuild is
        // false -- but an earlier confirm-summary message's readyToBuild
        // stays true forever in the list, so `.any` would show this button
        // alongside the "Plan each day" CTA above. readyToBuild and
        // awaitingStep are set together from the same currentStep on each
        // message (api_chat_repository.dart), so checking last keeps the
        // two states in this Column truly mutually exclusive.
        if (messages.isNotEmpty && messages.last.readyToBuild)
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
            child: SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                onPressed: onBuildItinerary,
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: AppColors.primary),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                child: Text(
                  'Ready? Build My Itinerary →',
                  style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700),
                ),
              ),
            ),
          ),
        if (sending) const _TypingBubble(),
        // The dates question is picker-only; the backend bounces typed
        // answers back to the calendar.
        if (messages.isNotEmpty &&
            messages.last.awaitingField == 'travel_dates')
          DateRangeAnswerBar(onPick: onPickDates),
        if (messages.isNotEmpty && messages.last.quickReplies.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            // Wrap, not Row: 'companion' offers four chips, which can
            // overflow a phone width on one line. Wrapping keeps every
            // option reachable — a horizontal scroller would hide some of
            // them off the right edge with no affordance saying so.
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final reply in messages.last.quickReplies)
                  Padding(
                    padding: EdgeInsets.zero,
                    child: ActionChip(
                      label: Text(reply, style: AppTextStyles.bodySmall),
                      onPressed: () => onQuickReply(reply),
                      backgroundColor: AppColors.surface,
                      side: const BorderSide(color: AppColors.primary),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(AppRadii.pill),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        Container(
          color: AppColors.composerBackground,
          padding: const EdgeInsets.all(16),
          child: Container(
            height: 54,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: BoxDecoration(
              color: AppColors.composerBackground,
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: composerController,
                    decoration: const InputDecoration(
                      hintText: 'Just traveling with my partner...',
                      border: InputBorder.none,
                    ),
                    style: AppTextStyles.bodyMedium,
                    onSubmitted: (_) => onSend(),
                  ),
                ),
                GestureDetector(
                  onTap: sending ? null : onSend,
                  child: Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: sending
                          ? AppColors.primary.withValues(alpha: 0.45)
                          : AppColors.primary,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: sending
                        ? const Padding(
                            padding: EdgeInsets.all(10),
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor:
                                  AlwaysStoppedAnimation<Color>(Colors.white),
                            ),
                          )
                        : const Icon(Icons.send, size: 16, color: Colors.white),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// A full-width outlined CTA under the message list, same shape as the
/// "Ready? Build My Itinerary" button above it — the two are mutually
/// exclusive states (`day_plan` vs. `confirm`) so only ever one shows, as
/// long as both gates read `messages.last` and nothing scans history.
class _CtaButton extends StatelessWidget {
  const _CtaButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
      child: SizedBox(
        width: double.infinity,
        child: OutlinedButton(
          onPressed: onPressed,
          style: OutlinedButton.styleFrom(
            side: const BorderSide(color: AppColors.primary),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            padding: const EdgeInsets.symmetric(vertical: 12),
          ),
          child: Text(
            label,
            style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700),
          ),
        ),
      ),
    );
  }
}

class _TravelerSelector extends StatelessWidget {
  const _TravelerSelector({required this.count, required this.onChange});

  final int count;
  final ValueChanged<int> onChange;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Padding(
            padding: const EdgeInsets.all(10),
            child: Row(
              children: [
                const Icon(Icons.people_outline, size: 16, color: AppColors.textPrimary),
                const SizedBox(width: 8),
                Text('$count Adults', style: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w600)),
              ],
            ),
          ),
          Row(
            children: [
              _stepButton(Icons.remove, () => onChange((count - 1).clamp(1, 10)), AppColors.surfaceMuted, AppColors.textPrimary),
              const SizedBox(width: 4),
              _stepButton(Icons.add, () => onChange((count + 1).clamp(1, 10)), AppColors.primary, Colors.white),
            ],
          ),
        ],
      ),
    );
  }

  Widget _stepButton(IconData icon, VoidCallback onTap, Color bg, Color fg) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 28,
        height: 28,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
        child: Icon(icon, size: 16, color: fg),
      ),
    );
  }
}

/// "In Seoul now?" -- the three on-trip topics people need in a hurry, one tap
/// from the Plan chat, plus a way into the full On-trip view.
class _OnTripHint extends StatelessWidget {
  const _OnTripHint({
    required this.onOpenTopic,
    required this.onShowAll,
    required this.onDismiss,
  });

  final void Function(LiveHelpTopic topic) onOpenTopic;
  final VoidCallback onShowAll;
  final VoidCallback onDismiss;

  static const _shortcuts = [
    LiveHelpTopic.nearby,
    LiveHelpTopic.emergency,
    LiveHelpTopic.passport,
  ];

  @override
  Widget build(BuildContext context) {
    final topics = context.read<ChatRepository>().onTripTopics();
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      padding: const EdgeInsets.fromLTRB(14, 10, 4, 10),
      decoration: BoxDecoration(
        color: const Color(0xFFEBF0EC),
        border: Border.all(color: const Color(0xFFCFDDD3)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '🧭 In Seoul now? Get help on the go',
                  style: AppTextStyles.bodySmall.copyWith(
                    fontWeight: FontWeight.w700,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final t in topics.where((t) => _shortcuts.contains(t.topic)))
                      _chip('${t.emoji} ${t.title}', () => onOpenTopic(t.topic)),
                    _chip('All on-trip help →', onShowAll, strong: true),
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            onPressed: onDismiss,
            tooltip: 'Hide',
            icon: const Icon(Icons.close, size: 16),
            color: AppColors.textSecondary,
            visualDensity: VisualDensity.compact,
          ),
        ],
      ),
    );
  }

  Widget _chip(String label, VoidCallback onTap, {bool strong = false}) {
    return Material(
      color: strong ? const Color(0xFF5E836A) : Colors.white,
      borderRadius: BorderRadius.circular(999),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          child: Text(
            label,
            style: AppTextStyles.caption.copyWith(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: strong ? Colors.white : AppColors.textPrimary,
            ),
          ),
        ),
      ),
    );
  }
}

class _OnTripView extends StatelessWidget {
  const _OnTripView({required this.onOpenTopic});

  final void Function(LiveHelpTopic topic) onOpenTopic;

  @override
  Widget build(BuildContext context) {
    final topics = context.read<ChatRepository>().onTripTopics();
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text('How can we help?', textAlign: TextAlign.center, style: AppTextStyles.headingLarge.copyWith(fontFamily: null, fontSize: 28, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(
            'Instant concierge assistance for travelers in Seoul',
            textAlign: TextAlign.center,
            style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: 24),
          for (final topic in topics) ...[
            _TopicCard(topic: topic, onTap: () => onOpenTopic(topic.topic)),
            const SizedBox(height: 16),
          ],
          Text(
            'Tap for instant results — no chat needed.',
            style: AppTextStyles.bodySmall.copyWith(color: AppColors.textSecondary.withValues(alpha: 0.8)),
          ),
        ],
      ),
    );
  }
}

class _TopicCard extends StatelessWidget {
  const _TopicCard({required this.topic, required this.onTap});

  final dynamic topic;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final badgeColors = <String, Color>{
      'urgent': const Color(0xFFD35D4A),
      '911': const Color(0xFFC4722A),
      'utility': const Color(0xFF5E836A),
    };
    final badgeBg = <String, Color>{
      'urgent': const Color(0xFFFFF0ED),
      '911': const Color(0xFFFFF3E8),
      'utility': const Color(0xFFEBF0EC),
    };
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: AppColors.borderAlt),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: AppColors.chipBackground,
                borderRadius: BorderRadius.circular(14),
              ),
              alignment: Alignment.center,
              child: Text(topic.emoji, style: const TextStyle(fontSize: 24)),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(topic.title, style: AppTextStyles.cardTitle.copyWith(fontSize: 16)),
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: badgeBg[topic.badge] ?? AppColors.chipBackground,
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          topic.badge.toString().toUpperCase(),
                          style: AppTextStyles.caption.copyWith(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: badgeColors[topic.badge] ?? AppColors.primary,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(topic.description, style: AppTextStyles.bodySmall),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textSecondary),
          ],
        ),
      ),
    );
  }
}

/// The buddy's "thinking" bubble.
///
/// A conversational turn is a Gemini call measured at 3-7s, and the confirm
/// turn runs the whole planner. Without this the chat simply sat still and
/// looked broken.
class _TypingBubble extends StatefulWidget {
  const _TypingBubble();

  @override
  State<_TypingBubble> createState() => _TypingBubbleState();
}

class _TypingBubbleState extends State<_TypingBubble>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1200),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Honours the platform reduced-motion setting: the bubble still shows,
    // it just holds still instead of looping.
    if (Motion.reduced(context)) {
      _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: const BoxDecoration(
            color: AppColors.bubbleBot,
            borderRadius: BorderRadius.only(
              topLeft: Radius.circular(16),
              topRight: Radius.circular(16),
              bottomRight: Radius.circular(16),
              bottomLeft: Radius.circular(4),
            ),
          ),
          child: AnimatedBuilder(
            animation: _controller,
            builder: (context, _) => Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (var i = 0; i < 3; i++)
                  Padding(
                    padding: EdgeInsets.only(right: i == 2 ? 0 : 5),
                    child: Opacity(
                      // Each dot leads the next by a third of the cycle.
                      opacity: 0.35 +
                          0.65 *
                              ((_controller.value + i / 3) % 1.0 < 0.5
                                  ? ((_controller.value + i / 3) % 1.0) * 2
                                  : (1 - ((_controller.value + i / 3) % 1.0)) *
                                      2),
                      child: Container(
                        width: 7,
                        height: 7,
                        decoration: const BoxDecoration(
                          color: AppColors.primary,
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
