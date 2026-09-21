import 'package:flutter/material.dart';

import '../../data/repositories/events_repository.dart';
import '../../models/event.dart';
import '../../theme/theme.dart';
import '../../widgets/data_source_note.dart';
import 'event_detail_sheet.dart';

class EventsScreen extends StatefulWidget {
  const EventsScreen({super.key, required this.repository});

  final EventsRepository repository;

  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends State<EventsScreen> {
  List<SeoulEvent> _events = [];
  String _category = kDefaultEventCategory;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final events = await widget.repository.fetchEvents(_category);
    if (!mounted) return;
    setState(() => _events = events);
  }

  void _selectCategory(String category) {
    if (category == _category) return;
    setState(() {
      _category = category;
      // Clear first: leaving the previous genre's posters up while the new
      // ones load reads as if the filter did nothing.
      _events = [];
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final displayed = _events;

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
                    Text(
                      'Events in Seoul',
                      style: AppTextStyles.headingMedium.copyWith(fontSize: 26),
                    ),
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
                  onTap: () => _selectCategory(category),
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
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: DataSourceNote(),
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

  /// Keyed on kEventCategories. A label with no entry just renders without an
  /// emoji, which is how the old nine ticket-genre keys failed silently after
  /// the chips moved to the Korea Tourism Organization's own classification.
  static const _emoji = {
    'All': '✨',
    'Festivals': '🎪',
    'Performances': '🎭',
    'Exhibitions': '🖼️',
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
    return GestureDetector(
      // Opens the detail sheet rather than kicking straight out to a browser.
      // Mock data has no contentid and no landing URL — nothing to show beyond
      // the card itself, so it stays inert there.
      onTap: event.contentId == null && event.landingUrl == null
          ? null
          : () => showEventDetailSheet(context, event),
      child: Container(
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
                  : event.posterUrl != null
                  ? Image.network(
                      event.posterUrl!,
                      width: double.infinity,
                      fit: BoxFit.cover,
                      // A dead poster URL must not blank the card — the title
                      // and venue underneath are the useful part.
                      errorBuilder: (_, _, _) => _PosterFallback(event: event),
                    )
                  : _PosterFallback(event: event),
            ),
            Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    event.dateRange,
                    style: AppTextStyles.caption.copyWith(
                      color: const Color(0xFFA67C68),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Text(
                    event.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.headingSmall.copyWith(fontSize: 15),
                  ),
                  Text(
                    '📍 ${event.venue}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.caption,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The gradient stand-in shown when an event has no artwork, or when its
/// remote poster fails to load.
class _PosterFallback extends StatelessWidget {
  const _PosterFallback({required this.event});

  final SeoulEvent event;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: event.posterColors,
        ),
      ),
    );
  }
}
