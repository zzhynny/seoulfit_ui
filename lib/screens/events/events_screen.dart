import 'package:flutter/material.dart';
import '../../data/repositories/events_repository.dart';
import '../../models/event.dart';
import '../../theme/theme.dart';

class EventsScreen extends StatefulWidget {
  const EventsScreen({super.key, required this.repository});

  final EventsRepository repository;

  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends State<EventsScreen> {
  List<SeoulEvent> _events = [];
  String _category = 'Musical';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final events = await widget.repository.fetchEvents();
    if (!mounted) return;
    setState(() => _events = events);
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _events.where((e) => e.category == _category).toList();
    final displayed = filtered.isEmpty ? _events : filtered;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 12, 24, 16),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Events in Seoul', style: AppTextStyles.headingMedium.copyWith(fontSize: 26)),
                    const SizedBox(height: 6),
                    Text(
                      'Discover performances, exhibitions and festivals during your trip',
                      style: AppTextStyles.bodySmall.copyWith(color: AppColors.textSecondary),
                    ),
                  ],
                ),
              ),
              GestureDetector(
                onTap: _load,
                child: Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: AppColors.borderAlt),
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: const Icon(Icons.refresh, size: 16),
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final category in kEventCategories)
                _CategoryChip(
                  label: category,
                  selected: category == _category,
                  onTap: () => setState(() => _category = category),
                ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Expanded(
          child: GridView.builder(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              crossAxisSpacing: 12,
              mainAxisSpacing: 12,
              childAspectRatio: 0.62,
            ),
            itemCount: displayed.length,
            itemBuilder: (context, index) => _EventCard(event: displayed[index]),
          ),
        ),
      ],
    );
  }
}

class _CategoryChip extends StatelessWidget {
  const _CategoryChip({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  static const _emoji = {
    'Musical': '🎭',
    'Concert': '🎤',
    'Exhibition': '🖼️',
    'Classic': '🎹',
    'Family': '👨‍👩‍👧',
    'Theater': '🎬',
  };

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 110,
        height: 42,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? const Color(0xFF5E836A) : AppColors.composerBackground,
          border: Border.all(color: AppColors.borderAlt),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          '${_emoji[label] ?? ''} $label',
          style: AppTextStyles.bodySmall.copyWith(
            color: selected ? Colors.white : AppColors.textPrimary,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
          ),
        ),
      ),
    );
  }
}

class _EventCard extends StatelessWidget {
  const _EventCard({required this.event});

  final SeoulEvent event;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.borderAlt),
        borderRadius: BorderRadius.circular(18),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: event.posterAsset != null
                ? Image.asset(event.posterAsset!, width: double.infinity, fit: BoxFit.cover)
                : Container(
                    width: double.infinity,
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: event.posterColors,
                      ),
                    ),
                  ),
          ),
          Padding(
            padding: const EdgeInsets.all(10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(event.dateRange, style: AppTextStyles.caption.copyWith(color: const Color(0xFFA67C68), fontWeight: FontWeight.w600)),
                Text(event.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppTextStyles.headingSmall.copyWith(fontSize: 15)),
                Text('📍 ${event.venue}', maxLines: 1, overflow: TextOverflow.ellipsis, style: AppTextStyles.caption),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
