class Admin::BaseController < ApplicationController
  layout 'admin'
  before_action :login_required

  private

  def login_required
    unless logged_in?
      redirect_to admin_login_path
    end
  end

end
