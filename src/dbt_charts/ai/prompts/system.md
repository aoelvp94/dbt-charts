{% if context_section -%}
{{ context_section }}
{% if sections or surface_suffix %}

---

{% endif -%}
{% endif -%}
{% for section in sections -%}
{{ section }}
{% if not loop.last or surface_suffix %}

---

{% endif -%}
{% endfor -%}
{% if surface_suffix -%}
{{ surface_suffix }}
{% endif -%}
