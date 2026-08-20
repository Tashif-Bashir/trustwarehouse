-- marketing_workspace.v_meta_lead_ad_match
--
-- Matches Meta leads to the ad that produced them. Priority order (lowest
-- number wins; a lead only resolves to exact_match if exactly one ad_id is
-- unambiguously found across all methods for that lead):
--
--   0  ad_id_param        - explicit ?ad_id=<numeric> query param on the
--                            landing URL (since ~18 Aug 2026 tagging change),
--                            matched only against real ad_ids from
--                            meta_creative_performance. Deterministic - no
--                            other candidate ad_id needs to be considered.
--   1  utm_content_ad_id  - ad_id found as a substring of utm_content
--   2  utm_term_ad_id     - ad_id found as a substring of utm_term
--   3  marketing_url_ad_id- ad_id found as a substring anywhere in the URL
--   4  utm_campaign_ad_id - ad_id found as a substring of utm_campaign
--                            (fallback bucket for anything else)
--
-- If exact_match fails (0 or >1 candidate ad_ids), falls through to the
-- utm_term slug-dictionary inference (inferred_match) and then the looser
-- concept-level slug match (concept_match), unchanged by the 20 Aug 2026
-- ad_id_param addition below.
--
-- 20 Aug 2026: added the ad_id_param method (priority 0) after Meta started
-- appending ad_id=<numeric> to landing URLs (~18 Aug). Existing methods are
-- untouched so the 15-19 Aug cohort (created before the URL carried ad_id)
-- keeps matching the old way.
CREATE OR REPLACE VIEW `trustwarehouse.marketing_workspace.v_meta_lead_ad_match` AS
WITH date_bounds AS (
  SELECT MIN(date) AS min_date, MAX(date) AS max_date
  FROM `trustwarehouse.marketing_workspace.meta_creative_performance`
),
leads AS (
  SELECT
    l.*,
    LOWER(TRIM(IFNULL(l.utm_campaign, ''))) AS utm_campaign_lower,
    LOWER(TRIM(IFNULL(l.utm_content, ''))) AS utm_content_lower,
    LOWER(TRIM(IFNULL(l.utm_term, ''))) AS utm_term_lower,
    LOWER(TRIM(IFNULL(l.utm_source, ''))) AS utm_source_lower,
    REGEXP_EXTRACT(l.marketing_url, r'[?&]ad_id=(\d+)') AS url_ad_id_param
  FROM `trustwarehouse.marketing_workspace.v_lead_attribution_corrected` l
  CROSS JOIN date_bounds b
  WHERE l.platform = 'Meta'
    AND l.created_date BETWEEN b.min_date AND b.max_date
),
ads AS (
  SELECT DISTINCT ad_id FROM `trustwarehouse.marketing_workspace.meta_creative_performance`
),
exact_candidates AS (
  SELECT
    l.lead_id,
    a.ad_id,
    CASE
      WHEN l.url_ad_id_param IS NOT NULL AND l.url_ad_id_param = a.ad_id THEN 'ad_id_param'
      WHEN STRPOS(IFNULL(l.utm_content, ''), a.ad_id) > 0 THEN 'utm_content_ad_id'
      WHEN STRPOS(IFNULL(l.utm_term, ''), a.ad_id) > 0 THEN 'utm_term_ad_id'
      WHEN STRPOS(IFNULL(l.marketing_url, ''), a.ad_id) > 0 THEN 'marketing_url_ad_id'
      ELSE 'utm_campaign_ad_id'
    END AS match_method,
    CASE
      WHEN l.url_ad_id_param IS NOT NULL AND l.url_ad_id_param = a.ad_id THEN 0
      WHEN STRPOS(IFNULL(l.utm_content, ''), a.ad_id) > 0 THEN 1
      WHEN STRPOS(IFNULL(l.utm_term, ''), a.ad_id) > 0 THEN 2
      WHEN STRPOS(IFNULL(l.marketing_url, ''), a.ad_id) > 0 THEN 3
      ELSE 4
    END AS priority
  FROM leads l
  CROSS JOIN ads a
  WHERE (l.url_ad_id_param IS NOT NULL AND l.url_ad_id_param = a.ad_id)
     OR STRPOS(CONCAT(IFNULL(l.utm_content, ''), ' ', IFNULL(l.utm_term, ''), ' ',
                      IFNULL(l.marketing_url, ''), ' ', IFNULL(l.utm_campaign, '')), a.ad_id) > 0
),
exact_match AS (
  SELECT lead_id, ad_id, match_method
  FROM exact_candidates
  QUALIFY COUNT(*) OVER (PARTITION BY lead_id) = 1
      AND ROW_NUMBER() OVER (PARTITION BY lead_id ORDER BY priority) = 1
),
slug_dictionary AS (
  SELECT * FROM UNNEST([
    STRUCT('madeinbritain' AS slug, ['made','britain'] AS required_tokens, CAST(NULL AS STRING) AS required_variant),
    ('oliviainstall', ['olivia','install'], NULL),
    ('blackradiator', ['black','radiator'], NULL),
    ('neosphoto', ['neos','image'], NULL),
    ('howtheneosworks', ['how','neos','works'], NULL),
    ('normorechargeandhope2', ['no','more','charge','hope'], '2'),
    ('nomorechargeandhope2', ['no','more','charge','hope'], '2'),
    ('retargeting', ['retargeting'], NULL),
    ('whiteradiatoronthewall', ['white','radiator','wall'], NULL),
    ('coldby5pm', ['cold','5','pm'], NULL),
    ('scottbuiltradiator', ['scott','built','radiator'], NULL),
    ('scottbuildingradiator', ['scott','built','radiator'], NULL),
    ('stillmadeinbritain', ['still','made','britain'], NULL),
    ('finlay', ['finlay'], NULL),
    ('matty_dannyinstall', ['matty','danny','install'], NULL),
    ('hollyspeaking', ['holly','speaking'], NULL),
    ('hollietalking', ['holly','speaking'], NULL),
    ('niall_speaking', ['niall'], NULL),
    ('nialltalking', ['niall'], NULL),
    ('blackradiatonwall', ['black','radiator'], NULL),
    ('teampassingtheball', ['passing','ball'], NULL),
    ('teampassingtheball2', ['passing','ball'], NULL),
    ('whiteradiatoronbrickwall', ['white','radiator','brickwall'], NULL),
    ('catgoalkeeper', ['cat','goalkeeper'], NULL),
    ('kostafixingradiator', ['kosta','fixing','radiator'], NULL),
    ('1600colours', ['1600','colours'], NULL),
    ('normorechargeandhope3', ['no','more','charge','hope'], '3'),
    ('redradiator', ['red','radiator'], NULL),
    ('scottandfionatrusthouse', ['scott','fiona','trust','house'], NULL),
    ('warmthformom', ['warmth','mom'], NULL),
    ('fionaspeaking', ['fiona','speaking'], NULL),
    ('heatwave1', ['heatwave'], '1'),
    ('thepuffectheat', ['puffect','heat'], NULL),
    ('realwarmthnopipeworks', ['real','warmth','no','pipeworks'], NULL),
    ('oliviaspeaking', ['olivia','speaking'], NULL),
    ('oliviatalksstyle', ['olivia','speaking','style'], NULL),
    ('fionaspeaking_apple', ['fiona','speaking','apple'], NULL),
    ('catwiththumpsups', ['cat','thumps','ups'], NULL)
  ])
),
daily_ad_base AS (
  SELECT DISTINCT
    p.date,
    p.ad_id,
    p.ad_name,
    LOWER(p.campaign_name) AS campaign_name_lower,
    t.format
  FROM `trustwarehouse.marketing_workspace.meta_creative_performance` p
  JOIN `trustwarehouse.marketing_workspace.v_meta_creative_taxonomy` t USING (ad_id)
),
daily_ads AS (
  SELECT
    a.*,
    ARRAY(
      SELECT DISTINCT CASE token
        WHEN 'radiators' THEN 'radiator'
        WHEN 'photos' THEN 'image'
        WHEN 'photo' THEN 'image'
        WHEN 'images' THEN 'image'
        WHEN 'talking' THEN 'speaking'
        WHEN 'talks' THEN 'speaking'
        WHEN 'hollie' THEN 'holly'
        WHEN 'kostas' THEN 'kosta'
        WHEN 'building' THEN 'built'
        ELSE token
      END
      FROM UNNEST(REGEXP_EXTRACT_ALL(LOWER(a.ad_name), r'[a-z]+|[0-9]+')) token
    ) AS tokens
  FROM daily_ad_base a
),
slug_leads AS (
  SELECT
    l.*, d.slug, d.required_tokens, d.required_variant
  FROM leads l
  JOIN slug_dictionary d ON d.slug = l.utm_term_lower
  LEFT JOIN exact_match e USING (lead_id)
  WHERE e.lead_id IS NULL AND l.utm_source_lower = 'facebookads'
),
slug_candidate_pool AS (
  SELECT
    l.lead_id, l.slug, l.required_tokens, l.required_variant, d.ad_id, d.tokens
  FROM slug_leads l
  JOIN daily_ads d ON d.date = l.created_date
    AND (
      d.format = 'other'
      OR l.utm_content_lower NOT IN ('video','image','photo','card1')
      OR (l.utm_content_lower = 'video' AND d.format = 'video')
      OR (l.utm_content_lower IN ('image','photo') AND d.format = 'image')
      OR (l.utm_content_lower = 'card1' AND d.format = 'carousel')
    )
    AND (
      l.utm_campaign_lower IN ('','test')
      OR (l.utm_campaign_lower = 'general' AND REGEXP_CONTAINS(d.campaign_name_lower, r'general|\buk\b'))
      OR (l.utm_campaign_lower IN ('northern','midldands','midlands','wales','scotland','london','yorkshire','southwest')
          AND REGEXP_CONTAINS(d.campaign_name_lower, REPLACE(l.utm_campaign_lower,'midldands','midlands')))
      OR (l.utm_campaign_lower = 'southeast' AND REGEXP_CONTAINS(d.campaign_name_lower, r'se & east|southeast|south east'))
      OR (l.utm_campaign_lower = 'summer' AND REGEXP_CONTAINS(d.campaign_name_lower, r'summer'))
      OR (l.utm_campaign_lower = 'worldcup' AND REGEXP_CONTAINS(d.campaign_name_lower, r'world ?cup'))
      OR (l.utm_campaign_lower LIKE 'retargeting%' AND REGEXP_CONTAINS(d.campaign_name_lower, r'retarget'))
    )
),
slug_candidates AS (
  SELECT
    lead_id, slug, ad_id,
    COUNT(*) OVER (PARTITION BY lead_id) AS candidate_count
  FROM slug_candidate_pool
  WHERE (SELECT COUNTIF(token IN UNNEST(tokens)) FROM UNNEST(required_tokens) token) >=
    ARRAY_LENGTH(required_tokens)
    AND CASE required_variant
      WHEN '1' THEN '1' IN UNNEST(tokens)
      WHEN '2' THEN '2' IN UNNEST(tokens)
      WHEN '3' THEN '3' IN UNNEST(tokens)
      ELSE TRUE
    END
),
inferred_match AS (
  SELECT
    lead_id,
    ad_id,
    CONCAT('utm_term_creative_slug:', slug) AS match_method
  FROM slug_candidates
  WHERE candidate_count = 1
),
concept_slug_leads AS (
  SELECT
    l.*, d.slug, d.required_tokens, d.required_variant
  FROM leads l
  JOIN slug_dictionary d ON d.slug = l.utm_term_lower
  LEFT JOIN exact_match e USING (lead_id)
  LEFT JOIN inferred_match i USING (lead_id)
  WHERE e.lead_id IS NULL AND i.lead_id IS NULL
),
concept_candidate_pool AS (
  SELECT
    l.lead_id, l.slug, l.required_tokens, l.required_variant, d.ad_name, d.tokens
  FROM concept_slug_leads l
  JOIN daily_ads d ON d.date = l.created_date
    AND (
      d.format = 'other'
      OR l.utm_content_lower NOT IN ('video','image','photo','card1')
      OR (l.utm_content_lower = 'video' AND d.format = 'video')
      OR (l.utm_content_lower IN ('image','photo') AND d.format = 'image')
      OR (l.utm_content_lower = 'card1' AND d.format = 'carousel')
    )
    AND (
      l.utm_campaign_lower IN ('','test')
      OR (l.utm_campaign_lower = 'general' AND REGEXP_CONTAINS(d.campaign_name_lower, r'general|\buk\b'))
      OR (l.utm_campaign_lower IN ('northern','midldands','midlands','wales','scotland','london','yorkshire','southwest')
          AND REGEXP_CONTAINS(d.campaign_name_lower, REPLACE(l.utm_campaign_lower,'midldands','midlands')))
      OR (l.utm_campaign_lower = 'southeast' AND REGEXP_CONTAINS(d.campaign_name_lower, r'se & east|southeast|south east'))
      OR (l.utm_campaign_lower = 'summer' AND REGEXP_CONTAINS(d.campaign_name_lower, r'summer'))
      OR (l.utm_campaign_lower = 'worldcup' AND REGEXP_CONTAINS(d.campaign_name_lower, r'world ?cup'))
      OR (l.utm_campaign_lower LIKE 'retargeting%' AND REGEXP_CONTAINS(d.campaign_name_lower, r'retarget'))
    )
  QUALIFY ROW_NUMBER() OVER (PARTITION BY l.lead_id, d.ad_name ORDER BY d.ad_id) = 1
),
concept_candidates AS (
  SELECT
    lead_id, slug, ad_name,
    COUNT(*) OVER (PARTITION BY lead_id) AS candidate_count
  FROM concept_candidate_pool
  WHERE (SELECT COUNTIF(token IN UNNEST(tokens)) FROM UNNEST(required_tokens) token) >=
    ARRAY_LENGTH(required_tokens)
    AND CASE required_variant
      WHEN '1' THEN '1' IN UNNEST(tokens)
      WHEN '2' THEN '2' IN UNNEST(tokens)
      WHEN '3' THEN '3' IN UNNEST(tokens)
      ELSE TRUE
    END
),
concept_match AS (
  SELECT
    lead_id,
    ad_name,
    CONCAT('utm_term_concept:', slug) AS concept_match_method
  FROM concept_candidates
  WHERE candidate_count = 1
)
SELECT
  l.lead_id,
  l.created_date,
  l.create_timestamp,
  l.utm_source,
  l.utm_medium,
  l.utm_campaign,
  l.utm_content,
  l.utm_term,
  l.marketing_url,
  l.marketing_region,
  l.enquiry_type,
  l.lead_status,
  l.domestic_lead_status,
  l.is_appointment,
  COALESCE(e.ad_id, i.ad_id) AS ad_id,
  COALESCE(e.match_method, i.match_method, 'unmatched') AS match_method,
  CASE WHEN e.ad_id IS NOT NULL THEN 'exact' WHEN i.ad_id IS NOT NULL THEN 'inferred' ELSE NULL END AS match_confidence,
  COALESCE(e.ad_id, i.ad_id) IS NOT NULL AS is_matched,
  c.ad_name AS concept_ad_name,
  c.concept_match_method
FROM leads l
LEFT JOIN exact_match e USING (lead_id)
LEFT JOIN inferred_match i USING (lead_id)
LEFT JOIN concept_match c USING (lead_id)
