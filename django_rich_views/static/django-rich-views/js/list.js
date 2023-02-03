"use strict";
/*
	JavasScript support for rich list view.
*/

function toggle_filters() {
	const current = $(".toggle")[0].style.visibility;
	if (current == "collapse")
		$(".toggle").css('visibility', 'visible');
	else
		$(".toggle").css('visibility', 'collapse');
}

function check_button(which_one) {
	$("#opt_elements_"+which_one).prop("checked", true);
}

function URLopts() {
	let opts = []

	// The basic formatting and layout options
	const elements = $('input[type=radio][name=opt_elements]:checked').attr('value');
	const complete = $('input[type=radio][name=opt_complete]:checked').attr('value');
	const link = $('input[type=radio][name=opt_link]:checked').attr('value');
	const menus = $('input[type=radio][name=opt_menus]:checked').attr('value');
	const index = $('#opt_index').is(':checked') ? "index" : "noindex";
	const key = $('#opt_key').is(':checked') ? "key" : "nokey";

	const ordering_opts = ordering_url_opts();
	let filter_opts = filter_url_opts();
	// The filter if specified on the URL may contain conditions the filter widget doesn't support
	// So if  URL supplied filter is not in the widget provided filter opts, include it
	for (let f in filters)
		if (filter_opts.indexOf(filters[f]) < 0)
			filter_opts.push(filters[f]);
	Object.freeze(filter_opts);

	if (elements != default_elements) opts.push(elements);
	if (complete != default_complete) opts.push(complete);
	if (link != default_link) opts.push(link);
	if (menus != default_menus) opts.push(menus);
	if (index != default_index) opts.push(index);
	if (key != default_key) opts.push(key);

	if (ordering_opts.length > 0) opts.push(ordering_opts.join("&"));
	if (filter_opts.length > 0) opts.push(filter_opts.join("&"));

	let url_opts = (opts.length > 0) ? "?" + opts.join("&") : ""

	// Add the global league filter to URL opts used in GET requests
	const league_id = $("#id_league_view").val();
	const delim = (opts.length > 0) ? "&" : "?";
	url_opts += (league_id == 0) ? "" : delim + "league=" + league_id;

	return url_opts;
}

let REQUEST = new XMLHttpRequest();
REQUEST.onreadystatechange = function () {
    // Process the returned JSON
	if (this.readyState === 4 && this.status === 200){
		const response = JSON.parse(this.responseText);
		$("#data").html(response.HTML);
		URL_ajax = response.json_URL
		window.history.pushState("","", response.view_URL);
		$("#reloading_icon").css("visibility", "hidden");
		$("#opt_brief").prop('disabled', false);
		$("#opt_verbose").prop('disabled', false);
		$("#opt_rich").prop('disabled', false);
		$("#opt_detail").prop('disabled', false);
		$("#opt_specified").prop('disabled', false);
	}
};

function reload(event) {
	$("#reloading_icon").css("visibility", "visible");
	$("#opt_brief").prop('disabled', true);
	$("#opt_verbose").prop('disabled', true);
	$("#opt_rich").prop('disabled', true);
	$("#opt_detail").prop('disabled', true);
	$("#opt_specified").prop('disabled', true);
	const url = URL_ajax + URLopts();
	REQUEST.open("GET", url, true);
	REQUEST.send(null);
}


// These functions need to be writen/tested/ and then made part of the widgets themselves.
// They are here for now to write and test before moving into widgets

// Filter widget code seems in order and tested bar:
// TODO: ignore options who have no value! Don't add them to fopts.
// TODO: Hmmm, have to support relations, like ranks_player (which should in fact be performances_player anyhow).
// datetime encoding is broken.

function filter_url_opts() {
	const widgetid = "session_filtering_widget";
	let fopts = [];

  	function CollectFilterField(index, value) {
  		const field = $(value);
  		console.log("CollectFilterField: " + field);

  		const opt = field.prop('name');

  		let val = null;
  		if (field.is("input"))
  			val = field.val();
  		else if (field.is("select"))
  			val = field.find(":selected").val();

		if (val != 'None' && val != "")
			fopts.push(opt + "=" + encodeURIComponent(val));
  	}

	$("#"+widgetid).find(":input[id^='filter_field']").each(CollectFilterField);
	return fopts;
}

function show_url() {
	const url = URL_page + URLopts();
	window.history.pushState("","", url);
}
