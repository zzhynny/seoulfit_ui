import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../data/repositories/chat_repository.dart';
import '../../models/chat.dart';
import '../../models/companion.dart';
import '../../widgets/animations.dart';
import 'date_range_answer.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';

enum ChatMode { plan, onTrip }

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.onOpenHelpTopic, required this.onBuildItinerary});

  final void Function(LiveHelpTopic topic) onOpenHelpTopic;
  final VoidCallback onBuildItinerary;

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
  final _composerController = TextEditingController();
  int _travelerCount = 2;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final messages = await context.read<ChatRepository>().fetchConversation();
    if (!mounted) return;
    setState(() => _messages = messages);
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
          if (_mode == ChatMode.plan)
            Row(
              children: [
                SizedBox(
                  width: 36,
                  height: 36,
                  child: Image.asset(companion.guideChatAsset, fit: BoxFit.contain),
                ),
                const SizedBox(width: 12),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('SeoulFit AI', style: AppTextStyles.headingSmall.copyWith(fontSize: 16)),
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
                        Text('Online Concierge', style: AppTextStyles.caption),
                      ],
                    ),
                  ],
                ),
              ],
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
          _pill(context, 'Plan', ChatMode.plan),
          _pill(context, 'On-trip', ChatMode.onTrip),
        ],
      ),
    );
  }

  Widget _pill(BuildContext context, String label, ChatMode value) {
    final selected = mode == value;
    return GestureDetector(
      onTap: () => onChanged(value),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
        decoration: BoxDecoration(
          color: selected ? AppColors.textPrimary : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(
          label,
          style: AppTextStyles.caption.copyWith(
            color: selected ? Colors.white : AppColors.textSecondary,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
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
        if (messages.any((m) => m.readyToBuild))
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
            // Wrap, not Row: 'category' offers five chips and 'region' four,
            // which overflow a phone width on one line. Wrapping keeps every
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
